# -*- coding: utf-8 -*-
'''
Author: Ioannis Kakogeorgiou
Email: gkakogeorgiou@gmail.com
Python Version: 3.7.10
Description: engineering_patches.py production of patches with indices, texture, lbp or (other) spatial features
             for the pixel-level semantic segmentation with random forest classifier.
'''
import os
import argparse
import rasterio
import numpy as np
from glob import glob
from tqdm import tqdm
from shutil import copyfile
import skimage
from skimage import feature
from skimage.feature import greycomatrix, graycoprops, local_binary_pattern
from skimage.color import rgb2gray
from functools import partial
from os.path import dirname as up
from joblib import Parallel, delayed


import warnings
warnings.filterwarnings("ignore")

data_path = '/data/sushen/marinedebris/MARIDA'

np.seterr(divide='ignore', invalid='ignore')

# Bands number is based on 
# 1:nm440  2:nm490  3:nm560  4:nm665  5:nm705  6:nm740  7:nm783  8:nm842  9:nm865  10:nm1600  11:nm2200

def ndvi(band4, band8):
    return (band8 - band4)/(band8 + band4)

def fai(band4, band8, band10):
    l_nir = 833.0
    l_red = 665.0
    l_swir = 1614.0
    
    r_acc = band4 + (band10 - band4)*(l_nir - l_red)/(l_swir - l_red)
    
    return band8 - r_acc

def fdi(band6, band8, band10):
    l_nir = 833.0
    l_redge = 740.0
    l_swir = 1614.0
    
    r_acc = band6 + 10*(band10 - band6)*(l_nir - l_redge)/(l_swir - l_redge)
    
    return band8 - r_acc

def si(band2, band3, band4):
    return ((1-band2)*(1-band3)*(1-band4))**(1/3)

def ndwi(band3, band8):
    return (band3 - band8)/(band3 + band8)

def nrd(band4, band8):
    return (band8 - band4)

def ndmi(band8, band10):
    return (band8 - band10)/(band8 + band10)

def bsi(band2, band4, band8, band10):
    return ((band10 + band4)-(band8 + band2))/((band10 + band4)+(band8 + band2))

# GLCM properties
def glcm_feature(matrix_coocurrence):
    contrast = skimage.feature.graycoprops(matrix_coocurrence, 'contrast')
    dissimilarity = skimage.feature.graycoprops(matrix_coocurrence, 'dissimilarity')
    homogeneity = skimage.feature.graycoprops(matrix_coocurrence, 'homogeneity')
    energy = skimage.feature.graycoprops(matrix_coocurrence, 'energy')
    correlation = skimage.feature.graycoprops(matrix_coocurrence, 'correlation')
    asm = skimage.feature.graycoprops(matrix_coocurrence, 'ASM')
    
    return contrast.item(), dissimilarity.item(), homogeneity.item(), energy.item(), correlation.item(), asm.item()

def indices(image):
    
    output_path = os.path.join(up(up(image)),'indices', '_'.join(os.path.basename(image).split('_')[:-1]))
    output_image = os.path.join(output_path, os.path.basename(image).split('.')[0] + '_si.tif')
    os.makedirs(output_path, exist_ok=True)
    
    # Read metadata of the initial image
    with rasterio.open(image, mode ='r') as src:
        tags = src.tags().copy()
        meta = src.meta

    # Update meta to reflect the number of layers
    meta.update(count = 8)

    # Write it to stack
    with rasterio.open(output_image, 'w', **meta) as dst:
        with rasterio.open(image, mode ='r') as src:
            NDVI = ndvi(src.read(4), src.read(8))
            dst.write_band(1, NDVI)

            FAI = fai(src.read(4), src.read(8), src.read(10))
            dst.write_band(2, FAI)

            FDI = fdi(src.read(6), src.read(8), src.read(10))
            dst.write_band(3, FDI)
            
            SI = si(src.read(2), src.read(3), src.read(4))
            dst.write_band(4, SI)
            
            NDWI = ndwi(src.read(3), src.read(8))
            dst.write_band(5, NDWI)
            
            NRD = nrd(src.read(4), src.read(8))
            dst.write_band(6, NRD)
            
            NDMI = ndmi(src.read(8), src.read(10))
            dst.write_band(7, NDMI)
            
            BSI = bsi(src.read(2), src.read(4), src.read(8), src.read(10))
            dst.write_band(8, BSI)

        dst.update_tags(**tags)

def texture(image, window_size = 13, max_value = 16):
    
    output_path = os.path.join(up(up(image)),'texture', '_'.join(os.path.basename(image).split('_')[:-1]))
    output_image = os.path.join(output_path, os.path.basename(image).split('.')[0] + '_glcm.tif')
    os.makedirs(output_path, exist_ok=True)
    
    # Read metadata of the initial image
    with rasterio.open(image, mode ='r') as src:
        tags = src.tags().copy()
        meta = src.meta
        dtype = src.read(1).dtype

    # Update meta to reflect the number of layers
    meta.update(count = 6)
    
    # Write it to stack
    with rasterio.open(output_image, 'w', **meta) as dst:
        with rasterio.open(image, mode ='r') as src:
            img = src.read((2,3,4)).astype(dtype).copy()
            
            # From RGB Composite to Grayscale
            img = np.moveaxis(img, [0, 1, 2], [2, 0, 1])
            rgb_composite = img[:,:,[2,1,0]]
            rgb_composite[rgb_composite<0.0]=0.0
            rgb_composite[rgb_composite>0.15]=0.15
            rgb_composite = (rgb_composite)/0.15
            gray = rgb2gray(rgb_composite)

            bins = np.linspace(0.00, 1.00,max_value)
            num_levels = max_value+1

            assert (window_size -1)%2==0
            
            #
            temp_gray = np.pad(gray, (window_size-1)//2, mode='reflect')

            features_results=np.zeros((gray.shape[0], gray.shape[1], 6), dtype=dtype)

            for col in range((window_size-1)//2, gray.shape[0]+(window_size-1)//2):
                for row in range((window_size-1)//2, gray.shape[0]+(window_size-1)//2):
                    temp_gray_window = temp_gray[row - (window_size -1)//2: row + (window_size -1)//2 + 1, 
                                                 col - (window_size -1)//2: col + (window_size -1)//2 + 1]

                    inds = np.digitize(temp_gray_window, bins)

                    # Calculate on E, NE, N, NW as well as symmetric. So calculation on all directions and with 1 pixel offset-distance
                    matrix_coocurrence = skimage.feature.graycomatrix(inds, [1], [0, np.pi/4, np.pi/2, 3*np.pi/4], levels=num_levels, normed=True, symmetric=True)

                    # Aggregate all directions
                    matrix_coocurrence = matrix_coocurrence.mean(3)[:,:,:,np.newaxis]

                    con, dis, homo, ener, cor, asm = glcm_feature(matrix_coocurrence)
                    features_results[row - (window_size -1)//2,col - (window_size -1)//2,0] = con
                    features_results[row - (window_size -1)//2,col - (window_size -1)//2,1] = dis
                    features_results[row - (window_size -1)//2,col - (window_size -1)//2,2] = homo
                    features_results[row - (window_size -1)//2,col - (window_size -1)//2,3] = ener
                    features_results[row - (window_size -1)//2,col - (window_size -1)//2,4] = cor
                    features_results[row - (window_size -1)//2,col - (window_size -1)//2,5] = asm
            
            dst.write_band(1, features_results[:,:,0])
            dst.write_band(2, features_results[:,:,1])
            dst.write_band(3, features_results[:,:,2])
            dst.write_band(4, features_results[:,:,3])
            dst.write_band(5, features_results[:,:,4])
            dst.write_band(6, features_results[:,:,5])

        dst.update_tags(**tags)
      
def main(options):
    patches = glob(os.path.join(options['path'], 'patches_floobj', '*/*.tif'))
    print(patches)
    counter_tex = 0

    # Indices
    for image in tqdm(patches):
        indices(image)


    # Textures
    # for image in tqdm(patches):
    #     texture(image, options['window_size'], options['max_value'])
    #     print(counter_tex)
    #     counter_tex += 1

    # Parallel(n_jobs=options['n_jobs'])(delayed(texture)(image, options['window_size'], options['max_value']) for image in tqdm(patches))

            
if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    # Options
    parser.add_argument('--path', default=data_path, help='Path to dataset')
    parser.add_argument('--type', default='indices', type=str, help=' Select between indices or texture or spatial or lbp')
    parser.add_argument('--n_jobs', default= -2, type=int, help='How many cores?')
    
    # GLCM options
    parser.add_argument('--window_size', default= 13, type=int, help='Size of the sliding window for the GLCM (use an odd number)')
    parser.add_argument('--max_value', default= 16, type=int, help=' Number of bins-levels for image quantization for the GLCM (use a power of two)')

    # LBP options
    parser.add_argument('--radius', default= 3, type=int, help='Radius of circle (spatial resolution of the operator)')
    parser.add_argument('--n_points', default= 24, type=int, help='Number of circularly symmetric neighbour set points (quantization of the angular space)')
    
    args = parser.parse_args()
    options = vars(args)  # convert to ordinary dict
    
    main(options)
