import os
import platform
import numpy as np
import re
from torchvision.utils import draw_segmentation_masks
import torchvision.transforms.functional as F
import glob
import os.path as osp
from torchvision.ops import masks_to_boxes
import torch
from torchvision.utils import draw_bounding_boxes
import matplotlib.pyplot as plt
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import json
from src.utils import target_2_json, target_2_torch
from src.plot_utils import xywh2xyxy
from collections import defaultdict
from src.plot_utils import plot_results_img
import cv2

#todo make only once the conversion

"""
TODO : 


Important
- add multiple criterias or range of criterias to study, not necessarily fixed (API ?)
- FIX colors that match background

Bonus
- add day/night in metadata ???
- FIX people's hair being black
"""

"""
from https://pytorch.org/vision/main/auto_examples/plot_repurposing_annotations.html
"""

import pandas as pd

excl_colors = [
    '(R=0.160640,G=0.000000,B=1.000000,A=1.000000)',
    '(R=0.143117,G=1.000000,B=0.000000,A=1.000000)',
]



def postprocess_mask(mask):

    # Heuristic to keep some blobs
    # 100 pixels min
    # other ideas :
    #   - look at the ratio between areas
    #   - look at how distant they are

    # Find contours

    # image = cv2.imread(png_path, cv2.IMREAD_GRAYSCALE)
    contours, _ = cv2.findContours((mask.numpy() * 255).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Calculate the area of each contour
    contour_areas = []
    for contour in contours:
        area = cv2.contourArea(contour)
        contour_areas.append(area)

    idx_contour_mask = {i for i, area in enumerate(contour_areas) if area > 100}

    # Create a blank image for plotting the contours
    # contour_image = np.zeros_like(img_semantic_seg)
    new_mask = np.zeros_like(mask).astype(np.uint8)

    if len(idx_contour_mask) < 3:
        print("Num of contours>100 is 2 or less, keeping")
        for idx_contour in idx_contour_mask:
            contour = contours[idx_contour]
            cv2.drawContours(new_mask, [contour], 0, (255), thickness=cv2.FILLED)
        info_mask = "kept"
    else:
        print("Num of contours>100 is 3 or more, disgarding")
        for idx_contour in idx_contour_mask:
            contour = contours[idx_contour]
            cv2.drawContours(new_mask, [contour], 0, (255), thickness=cv2.FILLED)
        info_mask = "ignored"

    return torch.tensor(new_mask), info_mask

#%% Functions

def creation_date(path_to_file):
    """
    Try to get the date that a file was created, falling back to when it was
    last modified if that isn't possible.
    See http://stackoverflow.com/a/39501288/1709587 for explanation.
    """
    if platform.system() == 'Windows':
        return os.path.getctime(path_to_file)
    else:
        stat = os.stat(path_to_file)
        try:
            return stat.st_birthtime
        except AttributeError:
            # We're probably on Linux. No easy way to get creation dates here,
            # so we'll settle for when its content was last modified.
            return stat.st_mtime

def code_rgba_str_2_code_rgba_float(x):
    # define the regular expression pattern to match the float values
    pattern = r'R=([\d\.]+),G=([\d\.]+),B=([\d\.]+),A=([\d\.]+)'
    # use re.findall() to extract the float values as strings
    float_strs = re.findall(pattern, x)[0]
    # convert the float strings to floats and store them in a tuple
    return tuple(map(float, float_strs))


def show(imgs):
    if not isinstance(imgs, list):
        imgs = [imgs]
    fix, axs = plt.subplots(ncols=len(imgs), squeeze=False)
    for i, img in enumerate(imgs):
        img = img.detach()
        img = F.to_pil_image(img)
        axs[0, i].imshow(np.asarray(img))
        axs[0, i].set(xticklabels=[], yticklabels=[], xticks=[], yticks=[])


def find_duplicate_indices(dictionary):
    value_indices = defaultdict(list)
    for key, value in dictionary.items():
        value_indices[value].append(key)

    duplicate_indices = [indices for indices in value_indices.values() if len(indices) > 1]
    return duplicate_indices

def get_twincity_boxes(img, metadata):

    problematic_colors = [
        (0.0, 1.0, 0.749918, 1.0),
        (0.0, 1.0, 0.749918, 1.0),
        (0.070666, 0.366667, 0.906666, 1.0),
    ]

    mask_list = []
    peds_list = []
    ped_idx_list = []
    infos_mask = []
    for i, ped_id in enumerate(metadata["peds"].keys()):
        if metadata["peds"][ped_id] not in excl_colors: #todo adapt to background colors
            code = code_rgba_str_2_code_rgba_float(metadata["peds"][ped_id])
            if code[3] != 0:
                pass
                #print("Warning : Alpha code is not 1")
            code_alpha_one = np.array((code[:3] + (1.0,)))
            mask = (1*torch.tensor(((img-code_alpha_one)**2).sum(axis=2) < 1e-4))
            if mask.sum() > 0:
                info_mask = "kept"
                if code in problematic_colors:
                    mask, info_mask = postprocess_mask(mask)
                    mask[mask == 255] = 1

                if mask.sum() > 0:
                    infos_mask.append(info_mask)
                    mask_list.append(mask)
                    peds_list.append(ped_id)
                    ped_idx_list.append(i)

    if len(mask_list) == 0:
        print(f"Warning, empty mask for {metadata['hour']}h-{metadata['weather']}-"
              f"{metadata['cameraRotation']['pitch']}")
        plt.imshow(img)
        plt.show()

    # Check one
    """
    i = 20
    ped_id = list(metadata["peds"].keys())[i]
    code = code_rgba_str_2_code_rgba_float(metadata["peds"][ped_id])
    mask = torch.tensor(((img - code) ** 2).sum(axis=2) < 1e-4)
    plt.imshow(mask)
    plt.show()
    

    plt.imshow(img[850:900, 750:760])
    plt.show()
    x0 = (0.16078432,0,1,1)
    dist = [((np.array(x0)-np.array(code_rgba_str_2_code_rgba_float(x)))**2).sum() for x in metadata["peds"].values()]
    print(np.min(dist), np.argmin(dist), list(metadata["peds"].values())[np.argmin(dist)])

    plt.imshow(img[250:270, 940:960])
    plt.show()
    x0 = [0.        , 1.        , 0.31764707, 1.        ]
    dist = [((np.array(x0)-np.array(code_rgba_str_2_code_rgba_float(x)))**2).sum() for x in metadata["peds"].values()]
    print(np.min(dist), np.argmin(dist), list(metadata["peds"].values())[np.argmin(dist)])

    """



    masks = torch.stack(mask_list)
    try:
        boxes = masks_to_boxes(masks)
    except:
        print("coucou")

    # Calculate the heights and areas of the boxes
    heights = boxes[:, 3] - boxes[:, 1]
    widths = boxes[:, 2] - boxes[:, 0]
    areas = widths * heights

    # Create a DataFrame with the heights and areas
    data = {'height': heights.numpy().tolist(),
            "width":widths.numpy().tolist(),
            "aspect_ratio": (widths/heights).numpy().tolist(),
            'area': areas.numpy().tolist(),
            'ped': peds_list,
            "ignore_region": 1*(np.array(infos_mask) == "ignored")
            # df["ignore_region"] = 0
            }
    df = pd.DataFrame(data)


    # All reasons to ignore boxes

    # bbox width > 500
    df.loc[df["width"] > 500, "ignore_region"] = 1

    # Get doublons
    duplicates = find_duplicate_indices(metadata["peds"])
    if len(duplicates) > 0:
        print("Warning, doublons in metadata")
        idx_duplicates = np.unique(np.concatenate(duplicates)).astype(int).tolist()
        df.loc[np.isin(df["ped"], idx_duplicates), "ignore_region"] = 1


    # Remove if area is way too big
    df = df[df["area"]<500000]
    boxes = torch.stack([bbox for i, bbox in enumerate(boxes) if i in df[df["area"]<500000].index], axis=0)
    return boxes, df

def get_dataset_from_folder(folder, max_samples_per_seq=101):

    version = "v5"
    folder_name = folder.split(version+"/")[1]
    root = f'/home/yahya/work/datasets/twincity-Unreal/{version}/'

    from configs_path import ROOT_DIR

    save_folder = f"{ROOT_DIR}/cache/data_preprocessing/twincity/{version}/{folder_name}"

    #save_folder = f"/home/yahya/work/code/pedestrian-detection-sensitivity-analysis/src/demos/data/preprocessing/motsynth/twincity/{version}/{folder_name}"
    os.makedirs(save_folder, exist_ok=True)

    path_df_gtbbox_metadata = osp.join(save_folder, f"df_gtbbox_{max_samples_per_seq}.csv")
    path_df_frame_metadata = osp.join(save_folder, f"df_frame_{max_samples_per_seq}.csv")
    path_df_sequence_metadata = osp.join(save_folder, f"df_sequence_{max_samples_per_seq}.csv")
    path_target = osp.join(save_folder, f"targets_{max_samples_per_seq}.json")

    try:
        print("Try")
        df_gtbbox_metadata = pd.read_csv(path_df_gtbbox_metadata)#.set_index(["frame_id", "id"])
        df_frame_metadata = pd.read_csv(path_df_frame_metadata)#.set_index("frame_id")
        df_sequence_metadata = pd.read_csv(path_df_sequence_metadata)
        with open(path_target) as jsonFile:
            targets = target_2_torch(json.load(jsonFile))
        print("End Try")

    except:

        metadata_path = glob.glob(osp.join(folder, "Metadata*"))[0]
        images_path_list = glob.glob(osp.join(folder, "*.png"))

        with open(metadata_path) as file:
            metadata = json.load(file)

        ordering = np.argsort([creation_date(x) for x in images_path_list])

        #%%


        img_annot_path_list = np.array(images_path_list)[ordering[::2]]
        img_rgb_path_list = np.array(images_path_list)[ordering[1::2]]

        #img_rgb = mpimg.imread(img_rgb_path_list[0])
        img_annot = mpimg.imread(img_annot_path_list[0])

        #%% for a tuple (img_rgb, img_annot) get all the bounding boxes

        img = img_annot

        df_gtbbox_list = []
        targets = {}
        frame_id_list = []
        df_frame_list = []

        for i, img_annot_path in enumerate(img_annot_path_list):

            if i>max_samples_per_seq:
                break

            img_annot = mpimg.imread(img_annot_path)
            bboxes, df = get_twincity_boxes(img_annot, metadata)

            #todo hack to set the anomalies as ignore regions
            # filter anomalies

            frame_id = img_annot_path.split("/Snapshot-2023-")[-1].split(".png")[0]
            df["frame_id"] = frame_id #todo frame_id should be the one of the rgb
            df["id"] = frame_id #todo have to choose a denomination

            target = [
                dict(
                    boxes=
                        bboxes)
                ]
            target[0]["labels"] = torch.tensor([0] * len(target[0]["boxes"]))
            targets[frame_id] = target
            frame_id_list.append(frame_id)

            #%% Check if everything OK
            """
            from torchvision.utils import draw_bounding_boxes
            img_rgb = mpimg.imread(img_rgb_path_list[0])
            img_rgb_torch = torch.tensor(img_rgb * 255, dtype=torch.uint8)[:, :, :3]
            img_rgb_torch = torch.swapaxes(img_rgb_torch, 0, 1)
            img_rgb_torch = torch.swapaxes(img_rgb_torch, 0, 2)
            drawn_boxes = draw_bounding_boxes(torch.tensor(img_rgb_torch), bboxes, colors="red")
            show(drawn_boxes)
            plt.show()
            """


            #df_frame_metadata = df_gtbbox_metadata.groupby("frame_id").apply(lambda x: x.mean(numeric_only=True))

            dict_frame_metadata = {
                "weather": metadata["weather"],
                #"frame_id": frame_id,
                "id": frame_id,
                "file_name": img_rgb_path_list[i].split("v5/")[1],
            }
            df_frame_metadata = pd.DataFrame(dict_frame_metadata, index=[frame_id])
            for col in df.mean(numeric_only=True).keys():
                df_frame_metadata[col] = df[col].mean()
            df_frame_metadata.index.name = "frame_id"





            df_gtbbox_list.append(df)
            df_frame_list.append(df_frame_metadata)

        df_frame_metadata = pd.concat(df_frame_list, axis=0)

        df_frame_metadata["pitch"] = metadata["cameraRotation"]["pitch"]
        df_frame_metadata["num_peds"] = len(metadata["peds"])
        df_frame_metadata["num_vehicles"] = metadata["vehiclesNb"]
        df_frame_metadata["hour"] = metadata["hour"]
        df_frame_metadata["is_night"] = metadata["hour"] > 21 or metadata[
            "hour"] < 6  # todo pas ouf, dépend du jour de l'année ...

        df_gtbbox_metadata = pd.concat(df_gtbbox_list, axis=0)
        df_sequence_metadata = pd.DataFrame() #todo for now


        img_path_list = img_rgb_path_list
        img_path = osp.join(root, df_frame_metadata["file_name"].iloc[0])
        frame_id = df_frame_metadata.index[0]
        #plot_results_img(img_path, frame_id, preds=None, targets=targets,
        #                 excl_gt_indices=None, ax=None)

        #%% Save folder files
        df_gtbbox_metadata.to_csv(path_df_gtbbox_metadata)
        df_frame_metadata.to_csv(path_df_frame_metadata)
        df_sequence_metadata.to_csv(path_df_sequence_metadata)
        with open(path_target, 'w') as f:
            json.dump(target_2_json(targets), f)

    metadatas = df_gtbbox_metadata, df_frame_metadata, df_sequence_metadata

    return root, targets, metadatas#, frame_id_list, img_path_list


def get_twincity_dataset(root, max_samples_per_seq=100):

    folders = glob.glob(osp.join(root, "*"))

    targets = {}
    frame_id_list = []
    img_path_list = []
    df_gtbbox_metadata_list = []
    df_frame_metadata_list = []
    df_sequence_metadata_list = []

    for folder in folders:
        print(f"Reading folder {folder}")
        _, targets_folder, metadatas_folder = get_dataset_from_folder(folder, max_samples_per_seq)

        df_gtbbox_metadata_folder, df_frame_metadata_folder, df_sequence_metadata_folder = metadatas_folder

        # add outputs to their respective structures
        targets.update(targets_folder)
        #frame_id_list += frame_id_list_folder
        #img_path_list += img_path_list_folder.tolist()
        df_frame_metadata_folder["seq_name"] = folder.split("/")[-1]
        df_gtbbox_metadata_list.append(df_gtbbox_metadata_folder)
        df_frame_metadata_list.append(df_frame_metadata_folder)
        df_sequence_metadata_list.append(df_sequence_metadata_folder)


    df_gtbbox_metadata = pd.concat(df_gtbbox_metadata_list, axis=0)
    df_frame_metadata = pd.concat(df_frame_metadata_list, axis=0)
    #df_sequence_metadata = pd.concat(df_sequence_metadata_list, axis=0)
    df_sequence_metadata = pd.DataFrame()

    df_gtbbox_metadata["id"] = list(range(len(df_gtbbox_metadata))) #todo better gtbbox id (suffix of frame_id ?)

    df_gtbbox_metadata = df_gtbbox_metadata.set_index(["frame_id", "id"])
    if df_frame_metadata.index.name != "frame_id":
        df_frame_metadata = df_frame_metadata.set_index("frame_id")

    mu = 0.4185
    std = 0.12016
    df_gtbbox_metadata["aspect_ratio_is_typical"] = np.logical_and(df_gtbbox_metadata["aspect_ratio"] < mu + std,
                                                                   df_gtbbox_metadata["aspect_ratio"] > mu - std)

    df_frame_metadata["num_pedestrian"] = df_gtbbox_metadata.groupby("frame_id").apply(len).loc[df_frame_metadata.index]

    return root, targets, df_gtbbox_metadata, df_frame_metadata, df_sequence_metadata





#%% Plot









"""
#%%
img = img_annot
img_rgb_torch = torch.tensor(img_rgb*255, dtype=torch.uint8)[:,:,:3]
img_rgb_torch = torch.swapaxes(img_rgb_torch, 0, 1)
img_rgb_torch = torch.swapaxes(img_rgb_torch, 0, 2)
plt.imshow(img)
plt.show()


from torchvision.utils import draw_bounding_boxes
drawn_boxes = draw_bounding_boxes(torch.tensor(img_rgb_torch), boxes,
                                  colors="red", width=4)
show(drawn_boxes)
plt.show()
"""
#todo remove the sky one




