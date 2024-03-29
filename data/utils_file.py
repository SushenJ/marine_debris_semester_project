import numpy as np
import rasterio as rio
from shapely.geometry import LineString, Polygon
import geopandas as gpd
import shapely

L1CBANDS = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B9", "B10", "B11", "B12"]
L2ABANDS = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B9", "B11", "B12"]


def pad(image, mask=None, output_size=64):
    # if feature is near the image border, image wont be the desired output size
    H, W = output_size, output_size
    c, h, w = image.shape
    dh = (H - h) / 2
    dw = (W - w) / 2
    image = np.pad(image, [(0, 0), (int(np.ceil(dh)), int(np.floor(dh))),
                           (int(np.ceil(dw)), int(np.floor(dw)))])

    if mask is not None:
        h, w = mask.shape
        dh = (H - h) / 2
        dw = (W - w) / 2
        mask = np.pad(mask, [(int(np.ceil(dh)), int(np.floor(dh))),
                             (int(np.ceil(dw)), int(np.floor(dw)))])

        return image, mask
    else:
        return image

def remove_lines_outside_bounds(lines, imagebounds):
    def within_image(geometry):
        left, bottom, right, top = geometry.bounds
        ileft, ibottom, iright, itop = imagebounds
        return ileft < left and iright > right and itop > top and ibottom < bottom

    return lines.loc[lines.geometry.apply(within_image)]

def read_tif_image(imagefile, window=None):
    # loading of the image
    with rio.open(imagefile, "r") as src:
        image = src.read(window=window)

        is_l1cimage = src.meta["count"] == 13  # flag if l1c (top-of-atm) or l2a (bottom of atmosphere) image

        # keep only 12 bands: delete 10th band (nb: 9 because start idx=0)
        if is_l1cimage:  # is L1C Sentinel 2 data
            image = image[[L1CBANDS.index(b) for b in L2ABANDS]]

        if window is not None:
            win_transform = src.window_transform(window)
        else:
            win_transform = src.transform
    return image, win_transform

def get_window(geometry, output_size, transform):
    if isinstance(geometry, shapely.geometry.base.BaseGeometry):
        left, bottom, right, top = geometry.bounds
    else: # geopandas series
        left, bottom, right, top = geometry.geometry.bounds

    pixel_size = transform.a

    width = right - left
    height = top - bottom

    buffer_left_right = (output_size * pixel_size - width) / 2
    left -= buffer_left_right
    right += buffer_left_right

    buffer_bottom_top = (output_size * pixel_size - height) / 2
    bottom -= buffer_bottom_top
    top += buffer_bottom_top

    return rio.windows.from_bounds(left, bottom, right, top, transform)

def line_is_closed(linestringgeometry):
    coordinates = np.stack(linestringgeometry.xy).T
    first_point = coordinates[0]
    last_point = coordinates[-1]
    return bool((first_point == last_point).all())

def split_line_gdf_into_segments(lines):
    def segments(curve):
        return list(map(LineString, zip(curve.coords[:-1], curve.coords[1:])))

    line_segments = []
    for geometry in lines.geometry:
        line_segments += segments(geometry)
    return gpd.GeoDataFrame(geometry=line_segments)
