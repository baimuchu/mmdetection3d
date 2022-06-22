# Copyright (c) OpenMMLab. All rights reserved.
"""Convert the annotation pkl to the standard format in OpenMMLab V2.0.

Example:
    python tools/data_converter/update_infos_to_v2.py
        --pkl ./data/kitti/kitti_infos_train.pkl
        --out-dir ./kitti_v2/
"""

import argparse
import copy
import time
from os import path as osp

import mmcv
import numpy as np


def get_empty_instance():
    """Empty annotation for single instance."""
    instance = dict(
        # (list[float], required): list of 4 numbers representing
        # the bounding box of the instance, in (x1, y1, x2, y2) order.
        bbox=None,
        # (int, required): an integer in the range
        # [0, num_categories-1] representing the category label.
        bbox_label=None,
        #  (list[float], optional): list of 7 (or 9) numbers representing
        #  the 3D bounding box of the instance,
        #  in [x, y, z, w, h, l, yaw]
        #  (or [x, y, z, w, h, l, yaw, vx, vy]) order.
        bbox_3d=None,
        # (bool, optional): Whether to use the
        # 3D bounding box during training.
        bbox_3d_isvalid=None,
        # (int, optional): 3D category label
        # (typically the same as label).
        bbox_label_3d=None,
        # (float, optional): Projected center depth of the
        # 3D bounding box compared to the image plane.
        depth=None,
        #  (list[float], optional): Projected
        #  2D center of the 3D bounding box.
        center_2d=None,
        # (int, optional): Attribute labels
        # (fine-grained labels such as stopping, moving, ignore, crowd).
        attr_label=None,
        # (int, optional): The number of LiDAR
        # points in the 3D bounding box.
        num_lidar_pts=None,
        # (int, optional): The number of Radar
        # points in the 3D bounding box.
        num_radar_pts=None,
        # (int, optional): Difficulty level of
        # detecting the 3D bounding box.
        difficulty=None,
        unaligned_bbox_3d=None)
    return instance


def get_empty_lidar_points():
    lidar_points = dict(
        # (int, optional) : Number of features for each point.
        num_pts_feats=None,
        # (str, optional): Path of LiDAR data file.
        lidar_path=None,
        # (list[list[float]]): Transformation matrix from lidar
        # or depth to image with shape [4, 4].
        lidar2img=None,
        # (list[list[float]], optional): Transformation matrix
        # from lidar to ego-vehicle
        # with shape [4, 4].
        # (Referenced camera coordinate system is ego in KITTI.)
        lidar2ego=None,
    )
    return lidar_points


def get_empty_radar_points():
    radar_points = dict(
        # (int, optional) : Number of features for each point.
        num_pts_feats=None,
        # (str, optional): Path of RADAR data file.
        radar_path=None,
        # Transformation matrix from lidar to
        # ego-vehicle with shape [4, 4].
        # (Referenced camera coordinate system is ego in KITTI.)
        radar2ego=None,
    )
    return radar_points


def get_empty_img_info():
    img_info = dict(
        # (str, required): the path to the image file.
        img_path=None,
        # (int) The height of the image.
        height=None,
        # (int) The width of the image.
        width=None,
        # (str, optional): Path of the depth map file
        depth_map=None,
        # (list[list[float]], optional) : Transformation
        # matrix from camera to image with
        # shape [3, 3], [3, 4] or [4, 4].
        cam2img=None,
        # (list[list[float]], optional) : Transformation
        # matrix from camera to ego-vehicle
        # with shape [4, 4].
        cam2ego=None)
    return img_info


def get_single_image_sweep():
    single_image_sweep = dict(
        # (float, optional) : Timestamp of the current frame.
        timestamp=None,
        # (list[list[float]], optional) : Transformation matrix
        # from ego-vehicle to the global
        ego2global=None,
        # (dict): Information of images captured by multiple cameras
        images=dict(
            CAM0=get_empty_img_info(),
            CAM1=get_empty_img_info(),
            CAM2=get_empty_img_info(),
            CAM3=get_empty_img_info(),
        ))
    return single_image_sweep


def get_single_lidar_sweep():
    single_lidar_sweep = dict(
        # (float, optional) : Timestamp of the current frame.
        timestamp=None,
        # (list[list[float]], optional) : Transformation matrix
        # from ego-vehicle to the global
        ego2global=None,
        # (dict): Information of images captured by multiple cameras
        lidar_points=get_empty_lidar_points())
    return single_lidar_sweep


def get_empty_standard_data_info():

    data_info = dict(
        # (str): Sample id of the frame.
        sample_id=None,
        # (str, optional): '000010'
        token=None,
        **get_single_image_sweep(),
        # (dict, optional): dict contains information
        # of LiDAR point cloud frame.
        lidar_points=get_empty_lidar_points(),
        # (dict, optional) Each dict contains
        # information of Radar point cloud frame.
        radar_points=get_empty_radar_points(),
        # (list[dict], optional): Image sweeps data.
        image_sweeps=[],
        instances=[],
        # (list[dict], optional): Required by object
        # detection, instance  to be ignored during training.
        instances_ignore=[],
        # (str, optional): Path of semantic labels for each point.
        pts_semantic_mask_path=None,
        # (str, optional): Path of instance labels for each point.
        pts_instance_mask_path=None)
    return data_info


def clear_instance_unused_keys(instance):
    keys = list(instance.keys())
    for k in keys:
        if instance[k] is None:
            del instance[k]
    return instance


def clear_data_info_unused_keys(data_info):
    keys = list(data_info.keys())
    empty_flag = True
    for key in keys:
        # we allow no annotations in datainfo
        if key == 'instances':
            empty_flag = False
            continue
        if isinstance(data_info[key], list):
            if len(data_info[key]) == 0:
                del data_info[key]
            else:
                empty_flag = False
        elif data_info[key] is None:
            del data_info[key]
        elif isinstance(data_info[key], dict):
            _, sub_empty_flag = clear_data_info_unused_keys(data_info[key])
            if sub_empty_flag is False:
                empty_flag = False
            else:
                # sub field is empty
                del data_info[key]
        else:
            empty_flag = False

    return data_info, empty_flag


def update_kitti_infos(pkl_path, out_dir):
    print(f'{pkl_path} will be modified.')
    if out_dir in pkl_path:
        print(f'Warning, you may overwriting '
              f'the original data {pkl_path}.')
        time.sleep(5)
    # TODO update to full label
    # TODO discuss how to process 'Van', 'DontCare'
    METAINFO = {
        'CLASSES': ('Pedestrian', 'Cyclist', 'Car', 'Van', 'Truck',
                    'Person_sitting', 'Tram', 'Misc'),
    }
    print(f'Reading from input file: {pkl_path}.')
    data_list = mmcv.load(pkl_path)
    print('Start updating:')
    converted_list = []
    for ori_info_dict in mmcv.track_iter_progress(data_list):
        temp_data_info = get_empty_standard_data_info()

        if 'plane' in ori_info_dict:
            temp_data_info['plane'] = ori_info_dict['plane']

        temp_data_info['sample_id'] = ori_info_dict['image']['image_idx']

        temp_data_info['images']['CAM0']['cam2img'] = ori_info_dict['calib'][
            'P0'].tolist()
        temp_data_info['images']['CAM1']['cam2img'] = ori_info_dict['calib'][
            'P1'].tolist()
        temp_data_info['images']['CAM2']['cam2img'] = ori_info_dict['calib'][
            'P2'].tolist()
        temp_data_info['images']['CAM3']['cam2img'] = ori_info_dict['calib'][
            'P3'].tolist()

        temp_data_info['images']['CAM2']['img_path'] = ori_info_dict['image'][
            'image_path'].split('/')[-1]
        h, w = ori_info_dict['image']['image_shape']
        temp_data_info['images']['CAM2']['height'] = h
        temp_data_info['images']['CAM2']['width'] = w
        temp_data_info['lidar_points']['num_pts_feats'] = ori_info_dict[
            'point_cloud']['num_features']
        temp_data_info['lidar_points']['lidar_path'] = ori_info_dict[
            'point_cloud']['velodyne_path'].split('/')[-1]

        rect = ori_info_dict['calib']['R0_rect'].astype(np.float32)
        Trv2c = ori_info_dict['calib']['Tr_velo_to_cam'].astype(np.float32)
        lidar2cam = rect @ Trv2c
        temp_data_info['images']['CAM2']['lidar2cam'] = lidar2cam.tolist()
        temp_data_info['images']['CAM0']['lidar2img'] = (
            ori_info_dict['calib']['P0'] @ lidar2cam).tolist()
        temp_data_info['images']['CAM1']['lidar2img'] = (
            ori_info_dict['calib']['P1'] @ lidar2cam).tolist()
        temp_data_info['images']['CAM2']['lidar2img'] = (
            ori_info_dict['calib']['P2'] @ lidar2cam).tolist()
        temp_data_info['images']['CAM3']['lidar2img'] = (
            ori_info_dict['calib']['P3'] @ lidar2cam).tolist()

        temp_data_info['lidar_points']['Tr_velo_to_cam'] = Trv2c.tolist()

        # for potential usage
        temp_data_info['images']['R0_rect'] = ori_info_dict['calib'][
            'R0_rect'].astype(np.float32).tolist()
        temp_data_info['lidar_points']['Tr_imu_to_velo'] = ori_info_dict[
            'calib']['Tr_imu_to_velo'].astype(np.float32).tolist()

        anns = ori_info_dict['annos']
        num_instances = len(anns['name'])

        ignore_class_name = set()
        instance_list = []
        for instance_id in range(num_instances):
            empty_instance = get_empty_instance()
            empty_instance['bbox'] = anns['bbox'][instance_id].tolist()

            if anns['name'][instance_id] in METAINFO['CLASSES']:
                empty_instance['bbox_label'] = METAINFO['CLASSES'].index(
                    anns['name'][instance_id])
            else:
                ignore_class_name.add(anns['name'][instance_id])
                empty_instance['bbox_label'] = -1

            empty_instance['bbox'] = anns['bbox'][instance_id].tolist()

            loc = anns['location'][instance_id]
            dims = anns['dimensions'][instance_id]
            rots = anns['rotation_y'][:, None][instance_id]
            gt_bboxes_3d = np.concatenate([loc, dims,
                                           rots]).astype(np.float32).tolist()
            empty_instance['bbox_3d'] = gt_bboxes_3d
            empty_instance['bbox_label_3d'] = copy.deepcopy(
                empty_instance['bbox_label'])
            empty_instance['bbox'] = anns['bbox'][instance_id].tolist()
            empty_instance['truncated'] = int(
                anns['truncated'][instance_id].tolist())
            empty_instance['occluded'] = anns['occluded'][instance_id].tolist()
            empty_instance['alpha'] = anns['alpha'][instance_id].tolist()
            empty_instance['score'] = anns['score'][instance_id].tolist()
            empty_instance['index'] = anns['index'][instance_id].tolist()
            empty_instance['group_id'] = anns['group_ids'][instance_id].tolist(
            )
            empty_instance['difficulty'] = anns['difficulty'][
                instance_id].tolist()
            empty_instance['num_lidar_pts'] = anns['num_points_in_gt'][
                instance_id].tolist()
            empty_instance = clear_instance_unused_keys(empty_instance)
            instance_list.append(empty_instance)
        temp_data_info['instances'] = instance_list
        temp_data_info, _ = clear_data_info_unused_keys(temp_data_info)
        converted_list.append(temp_data_info)
    pkl_name = pkl_path.split('/')[-1]
    out_path = osp.join(out_dir, pkl_name)
    print(f'Writing to output file: {out_path}.')
    print(f'ignore classes: {ignore_class_name}')
    converted_data_info = dict(
        metainfo={'DATASET': 'KITTI'}, data_list=converted_list)

    mmcv.dump(converted_data_info, out_path, 'pkl')


def update_scannet_infos(pkl_path, out_dir):
    print(f'{pkl_path} will be modified.')
    if out_dir in pkl_path:
        print(f'Warning, you may overwriting '
              f'the original data {pkl_path}.')
        time.sleep(5)
    METAINFO = {
        'CLASSES':
        ('cabinet', 'bed', 'chair', 'sofa', 'table', 'door', 'window',
         'bookshelf', 'picture', 'counter', 'desk', 'curtain', 'refrigerator',
         'showercurtrain', 'toilet', 'sink', 'bathtub', 'garbagebin')
    }
    print(f'Reading from input file: {pkl_path}.')
    data_list = mmcv.load(pkl_path)
    print('Start updating:')
    converted_list = []
    for ori_info_dict in mmcv.track_iter_progress(data_list):
        temp_data_info = get_empty_standard_data_info()
        temp_data_info['lidar_points']['num_pts_feats'] = ori_info_dict[
            'point_cloud']['num_features']
        temp_data_info['lidar_points']['lidar_path'] = ori_info_dict[
            'pts_path'].split('/')[-1]
        temp_data_info['pts_semantic_mask_path'] = ori_info_dict[
            'pts_semantic_mask_path'].split('/')[-1]
        temp_data_info['pts_instance_mask_path'] = ori_info_dict[
            'pts_instance_mask_path'].split('/')[-1]

        # TODO support camera
        # np.linalg.inv(info['axis_align_matrix'] @ extrinsic): depth2cam
        anns = ori_info_dict['annos']
        temp_data_info['axis_align_matrix'] = anns['axis_align_matrix'].tolist(
        )
        if anns['gt_num'] == 0:
            instance_list = []
        else:
            num_instances = len(anns['name'])
            ignore_class_name = set()
            instance_list = []
            for instance_id in range(num_instances):
                empty_instance = get_empty_instance()
                empty_instance['bbox_3d'] = anns['gt_boxes_upright_depth'][
                    instance_id].tolist()

                if anns['name'][instance_id] in METAINFO['CLASSES']:
                    empty_instance['bbox_label_3d'] = METAINFO[
                        'CLASSES'].index(anns['name'][instance_id])
                else:
                    ignore_class_name.add(anns['name'][instance_id])
                    empty_instance['bbox_label_3d'] = -1

                empty_instance = clear_instance_unused_keys(empty_instance)
                instance_list.append(empty_instance)
        temp_data_info['instances'] = instance_list
        temp_data_info, _ = clear_data_info_unused_keys(temp_data_info)
        converted_list.append(temp_data_info)
    pkl_name = pkl_path.split('/')[-1]
    out_path = osp.join(out_dir, pkl_name)
    print(f'Writing to output file: {out_path}.')
    print(f'ignore classes: {ignore_class_name}')
    converted_data_info = dict(
        metainfo={'DATASET': 'SCANNET'}, data_list=converted_list)

    mmcv.dump(converted_data_info, out_path, 'pkl')


def update_sunrgbd_infos(pkl_path, out_dir):
    print(f'{pkl_path} will be modified.')
    if out_dir in pkl_path:
        print(f'Warning, you may overwriting '
              f'the original data {pkl_path}.')
        time.sleep(5)
    METAINFO = {
        'CLASSES': ('bed', 'table', 'sofa', 'chair', 'toilet', 'desk',
                    'dresser', 'night_stand', 'bookshelf', 'bathtub')
    }
    print(f'Reading from input file: {pkl_path}.')
    data_list = mmcv.load(pkl_path)
    print('Start updating:')
    converted_list = []
    for ori_info_dict in mmcv.track_iter_progress(data_list):
        temp_data_info = get_empty_standard_data_info()
        temp_data_info['lidar_points']['num_pts_feats'] = ori_info_dict[
            'point_cloud']['num_features']
        temp_data_info['lidar_points']['lidar_path'] = ori_info_dict[
            'pts_path'].split('/')[-1]
        calib = ori_info_dict['calib']
        rt_mat = calib['Rt']
        # follow Coord3DMode.convert_point
        rt_mat = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]
                           ]) @ rt_mat.transpose(1, 0)
        depth2img = calib['K'] @ rt_mat
        temp_data_info['images']['CAM0']['depth2img'] = depth2img.tolist()
        temp_data_info['images']['CAM0']['img_path'] = ori_info_dict['image'][
            'image_path'].split('/')[-1]
        h, w = ori_info_dict['image']['image_shape']
        temp_data_info['images']['CAM0']['height'] = h
        temp_data_info['images']['CAM0']['width'] = w

        anns = ori_info_dict['annos']
        num_instances = len(anns['name'])
        ignore_class_name = set()
        instance_list = []
        for instance_id in range(num_instances):
            empty_instance = get_empty_instance()
            empty_instance['bbox_3d'] = anns['gt_boxes_upright_depth'][
                instance_id].tolist()
            if anns['name'][instance_id] in METAINFO['CLASSES']:
                empty_instance['bbox_label_3d'] = METAINFO['CLASSES'].index(
                    anns['name'][instance_id])
            else:
                ignore_class_name.add(anns['name'][instance_id])
                empty_instance['bbox_label_3d'] = -1
            empty_instance = clear_instance_unused_keys(empty_instance)
            instance_list.append(empty_instance)
        temp_data_info['instances'] = instance_list
        temp_data_info, _ = clear_data_info_unused_keys(temp_data_info)
        converted_list.append(temp_data_info)
    pkl_name = pkl_path.split('/')[-1]
    out_path = osp.join(out_dir, pkl_name)
    print(f'Writing to output file: {out_path}.')
    print(f'ignore classes: {ignore_class_name}')
    converted_data_info = dict(
        metainfo={'DATASET': 'SUNRGBD'}, data_list=converted_list)

    mmcv.dump(converted_data_info, out_path, 'pkl')


def parse_args():
    parser = argparse.ArgumentParser(description='Arg parser for data coords '
                                     'update due to coords sys refactor.')
    parser.add_argument(
        '--dataset', type=str, default='kitti', help='name of dataset')
    parser.add_argument(
        '--pkl',
        type=str,
        default='./data/kitti/kitti_infos_train.pkl ',
        help='specify the root dir of dataset')

    parser.add_argument(
        '--out-dir',
        type=str,
        default='converted_annotations',
        required=False,
        help='output direction of info pkl')
    args = parser.parse_args()
    return args


def main():
    args = parse_args()
    if args.out_dir is None:
        args.out_dir = args.root_dir
    if args.dataset.lower() == 'kitti':
        update_kitti_infos(pkl_path=args.pkl, out_dir=args.out_dir)
    elif args.dataset.lower() == 'scannet':
        update_scannet_infos(pkl_path=args.pkl, out_dir=args.out_dir)
    elif args.dataset.lower() == 'sunrgbd':
        update_sunrgbd_infos(pkl_path=args.pkl, out_dir=args.out_dir)
    else:
        raise NotImplementedError(
            f'Do not support convert {args.dataset} to v2.')


if __name__ == '__main__':
    main()
