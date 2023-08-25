import heapq
import random
import json
import tracemalloc
from collections import defaultdict
import numpy as np
import copy
import torch
from itertools import permutations
from botorch.models import SingleTaskGP
from botorch.fit import fit_gpytorch_model
from botorch.utils import standardize
from gpytorch.mlls import ExactMarginalLogLikelihood
from botorch.acquisition import UpperConfidenceBound
from botorch.optim import optimize_acqf
from sklearn.decomposition import PCA
import cv2
import time
import random
from MOT_demo_v14_based_on_reid_v22_notstandard_yolov5_add_face_remove_skeleton_ref import *
from contextlib import ExitStack
from torch.quasirandom import SobolEngine
import gpytorch
import gpytorch.settings as gpts
import pykeops
from botorch.fit import fit_gpytorch_model
from botorch.generation import MaxPosteriorSampling
from botorch.models import SingleTaskGP
from botorch.test_functions import Hartmann
from botorch.utils.transforms import unnormalize
from gpytorch.constraints import Interval
from gpytorch.distributions import MultivariateNormal
from gpytorch.kernels import MaternKernel, RFFKernel, ScaleKernel
from gpytorch.kernels.keops import MaternKernel as KMaternKernel
from gpytorch.likelihoods import GaussianLikelihood
from gpytorch.mlls import ExactMarginalLogLikelihood
import ot
import itertools

######################################################################################################################################################
################################## EM algorithm ######################################################################################################
def Gaussian_probability(input_vector, mean_vector, covariance_matrix):
    # return multivariate_normal.pdf(input_vector, mean=mean_vector, cov=covariance_matrix) # np.random.multivariate_normal(mean_vector, covariance_matrix, (len(input_vector), len(input_vector))) # (1 / np.sqrt(((2 * np.pi) ** len(input_vector)) * np.linalg.det(covariance_matrix))) * np.exp(-1 / (2 * covariance_matrix) * (np.linalg.norm(input_vector - mean_vector) ** 2))
    return 1 / (((2*np.pi)**(len(input_vector)/2)) * (np.linalg.det(covariance_matrix) ** (1/2))) * np.exp(-1 / 2 * np.matmul(np.matmul((input_vector - mean_vector).reshape(1, len(input_vector)), np.linalg.inv(covariance_matrix)), (input_vector - mean_vector).reshape(len(input_vector), 1)))

def np_cov(input_vector, num_components):
    return np.matmul(input_vector.reshape((num_components, 1)), input_vector.reshape((1, num_components)))

def obtain_num_components(split_each_track, mapping_node_id_to_features):
    rank_list = []
    for track_id in split_each_track:
        init_matrix = np.zeros((len(mapping_node_id_to_features[1]), len(mapping_node_id_to_features[1]))).astype('float32')
        for node_details in [x for x in split_each_track[track_id] if (int(x[0]) % 2 == 1 and int(x[1]) % 2 == 0 and int(x[0])-int(x[1])==-1)]:
            init_matrix += np.matmul(np.array(mapping_node_id_to_features[int(int(node_details[1])/2)]).reshape(512,1), np.array(mapping_node_id_to_features[int(int(node_details[1])/2)]).reshape(1, 512))
        rank_list.append(np.linalg.matrix_rank(init_matrix))
    assert(min(rank_list) > 2)
    return min(rank_list) - 1

def binary2int(input_data):
    binaryweight = np.array([2**(len(input_data) - 1 - x) for x in range(len(input_data))])
    return np.sum(input_data * binaryweight)

def decimal2int(input_data):
    binaryweight = np.array([10**(len(input_data) - 1 - x) for x in range(len(input_data))])
    return np.sum(input_data * binaryweight)



######################BO Optimization####################
def convert_track_to_bbox_list(split_each_track,mapping_node_id_to_bbox,mapping_node_id_to_belonglings):
    # 应该track当中严格属于某一条轨迹的点才能用于该段的拟合?
    # predicted_tracks_confidence_score = {}
    predicted_tracks_centers = {}
    predicted_tracks_bboxes = {}
    predicted_tracks_bboxes_test = {}
    mapping_frameid_to_human_centers = {}  # 暂存current_video_segment_predicted_tracks的value
    mapping_frameid_to_bbox = {}
    for track_id in split_each_track:
        # current_video_segment_predicted_tracks[track_id] = mapping_frameid_to_human_centers
        mapping_track_time_to_bbox = {} # 测试使用，保存该条轨迹每个时间点对应的bbox和帧数
        # mapping_frameid_to_confidence_score = {}
        confidence_score_max = 0
        node_id_max = 0
        # print(track_id,' started!' )
        for idx,node_pair in enumerate(split_each_track[track_id]):
            if int(node_pair[1]) % 2 == 0 and len(mapping_node_id_to_belonglings[int(node_pair[1]) / 2]) == 1 and mapping_node_id_to_belonglings[int(node_pair[1]) / 2][0] == track_id : # 只保留绝对正确的点，唯一的时候确保其唯一为当前轨迹
                node_id = int(node_pair[1]) / 2
                # print(node_id)
            else:
                continue
            # mapping_node_id_to_bbox[mapping_node_id_to_bbox.index(int(node_pair[0]))][2] # str:img
            frame_id = mapping_node_id_to_bbox[node_id][2]  # 转化为int进行加减
            # print(node_id)
            bbox = mapping_node_id_to_bbox[node_id][0]
            confidence_score = mapping_node_id_to_bbox[node_id][1]
            if confidence_score > confidence_score_max:
                confidence_score_max = confidence_score
                node_id_max = node_id
            mapping_frameid_to_human_centers[int(frame_id.split('.')[0])] = [(bbox[0][0] + bbox[1][0]) / 2,
                                                                             (bbox[0][1] + bbox[1][1]) / 2]  # 同一帧中图片相连?
            mapping_frameid_to_bbox[frame_id] = bbox  # 如果是同一帧当中的图片只会保留最后一张
            mapping_track_time_to_bbox[int(node_id)] = [frame_id,bbox,confidence_score]
            # mapping_frameid_to_bbox[frame_id] = [bbox,confidence_score]
            # mapping_frameid_to_confidence_score[frame_id] = confidence_score

        predicted_tracks_centers[track_id] = copy.deepcopy(mapping_frameid_to_human_centers)
        predicted_tracks_bboxes[track_id] = copy.deepcopy(mapping_frameid_to_bbox)
        predicted_tracks_bboxes_test[track_id] = copy.deepcopy(mapping_track_time_to_bbox)
        mapping_frameid_to_human_centers.clear()
        mapping_frameid_to_bbox.clear()
        #mapping_frameid_to_bbox = {}
    return predicted_tracks_centers,predicted_tracks_bboxes,predicted_tracks_bboxes_test

def filter_out_invalid_mapping_node_id_to_belonglings(input_mapping_node_id_to_belongings,mapping_node_id_to_bbox,predicted_tracks_centers,predicted_tracks_bboxes,curr_batch_frame_node_list):
    '''
    解决同一帧物体当中分配同一个id的问题
    '''
    global batch_stride
    unique_frame_list = sorted(np.unique([mapping_node_id_to_bbox[x][2] for x in mapping_node_id_to_bbox])) # 当前batch包含的所有帧
    output_mapping_node_id_to_belongings = copy.deepcopy(input_mapping_node_id_to_belongings)

    belongings_length_list = [len(input_mapping_node_id_to_belongings[i]) for i in input_mapping_node_id_to_belongings] # 每个点可能情况的个数
    fix_node_list = [x for x in input_mapping_node_id_to_belongings if belongings_length_list[x-1]>=3] # 大于3种的key组成的列表
    fix_node_belongings = [input_mapping_node_id_to_belongings[x] for x in fix_node_list]  # 需要修正的点可能属于的列表集合.
    fix_node_information = [mapping_node_id_to_bbox[x] for x in fix_node_list]  # 需要修正的点的坐标以及置信度等信息
    belongings_length_dict = defaultdict(list) #
    for index,val in enumerate(belongings_length_list):
        belongings_length_dict[val].append(index)  # key:表示值 value:为索引列表
    maxlength_list_index = np.unique(belongings_length_dict[heapq.nlargest(2,belongings_length_list)[0]] + belongings_length_dict[heapq.nlargest(2,belongings_length_list)[1]]).tolist()[0:2] # 最大数的两个索引
    # maxlength_list_index = np.unique(list(map(belongings_length_list.index,heapq.nlargest(3,belongings_length_list)))).tolist() # 最大的两个索引 ???为什么会一样
    # maxlength_list_index = maxlength_list_index[0:-1] if len(maxlength_list_index)==3 else maxlength_list_index
    # ## 最多的两个轨迹的交集
    # common_tracks = list(set(input_mapping_node_id_to_belongings[maxlength_list_index[0]+1]).intersection(input_mapping_node_id_to_belongings[maxlength_list_index[1]+1]))
    # common_tracks = [track_id for track_id in common_tracks if len(predicted_tracks_centers[track_id])>1] # 保留包含中心点个数大于2的轨迹
    ## 所有多于两个点的轨迹
    common_tracks = [track_id for track_id in predicted_tracks_centers if len(predicted_tracks_centers[track_id])>1]
    ## 去掉点为1的轨迹(前面轨迹当中)
    ## 还会有轨迹当中一个绝对正确的点都没有
    for track_id in range(len(predicted_tracks_centers)-1): # 不包含最后一条轨迹
        track_id += 1
        if len(predicted_tracks_centers[track_id]) == 1:
            ##  如果这个点在后面几帧出现
            if unique_frame_list.index(predicted_tracks_centers[track_id].keys()[0]) > 7:
                batch_stride += 1
            del predicted_tracks_centers[track_id]
            del predicted_tracks_bboxes[track_id]

    # fix_node_list = list(set([belongings_length_list.index(x)+1 for x in belongings_length_list if x >= len(common_tracks)])) # 保证唯一  索引只会取到第一个所以结果不正确    # ????算出来的需要修正的点列不对 # keys,即node,不能保证一定包含所有的common_tracks
    node_track_mapping_matrix = np.zeros([len(fix_node_list),len(common_tracks)]) # 存储每个点到每条轨迹的拟合误差
    for node_id in fix_node_list: # 根据node id可以求出frame id作为自变量
        for track_id in common_tracks:
            node_id_frame = int(mapping_node_id_to_bbox[node_id][2].split('.')[0])
            node_id_center = [(mapping_node_id_to_bbox[node_id][0][0][0]+mapping_node_id_to_bbox[node_id][0][1][0])/2,(mapping_node_id_to_bbox[node_id][0][0][1]+mapping_node_id_to_bbox[node_id][0][1][1])/2]
            polyfit_x = [x for x in predicted_tracks_centers[track_id].keys()] # 以所在的帧数作为自变量
            if node_id_frame in polyfit_x: # 原来的轨迹已经包含该帧,很大概率原来的轨迹没有问题
                node_track_mapping_matrix[fix_node_list.index(node_id), common_tracks.index(track_id)] = 10000
                continue
            polyfit_x.append(node_id_frame)
            polyfit_x = np.unique(sorted(polyfit_x)).tolist()

            polyfit_y = [predicted_tracks_centers[track_id][frameid][0] for frameid in predicted_tracks_centers[track_id]] # 水平拟合
            polyfit_y.insert(polyfit_x.index(node_id_frame),node_id_center[0])  # index,obj
            polyfit_z = [predicted_tracks_centers[track_id][frameid][1] for frameid in predicted_tracks_centers[track_id]] # 垂直拟合
            polyfit_z.insert(polyfit_x.index(node_id_frame),node_id_center[1])
            # polyfit_x = range(len(predicted_tracks_centers)) # 总个数
            # 大于2的时候才能进行拟合?
            # if len(polyfit_x) > 2:
            node_track_mapping_matrix[fix_node_list.index(node_id),common_tracks.index(track_id)] = np.polyfit(polyfit_x, polyfit_y, 1, full=True)[1][0]+ np.polyfit(polyfit_x, polyfit_z, 1, full=True)[1][0]
    if common_tracks == []:
        return output_mapping_node_id_to_belongings
    for node_id in fix_node_list:  # 也有可能common tracks当中本身没有问题
        if min(node_track_mapping_matrix[fix_node_list.index(node_id),:])>100: # 该点与common tracks当中轨迹匹配误差都很大
            # # 去掉当中大于等于10000的
            # if min(node_track_mapping_matrix[fix_node_list.index(node_id), :]) < 10000:
            invalid_index = np.argwhere(np.array(node_track_mapping_matrix[fix_node_list.index(node_id),:]) >= 10000).flatten() #需要去掉的索引
            #output_mapping_node_id_to_belongings[node_id] = np.delete(output_mapping_node_id_to_belongings[node_id],[common_tracks[x] for x in invalid_index if common_tracks[x] in output_mapping_node_id_to_belongings[node_id]]).tolist() # 需要修正的点当中不一定包含所有的common_tracks
            output_mapping_node_id_to_belongings[node_id] = list(set(output_mapping_node_id_to_belongings[node_id])-set([common_tracks[x] for x in invalid_index if common_tracks[x] in output_mapping_node_id_to_belongings[node_id]])) # 需要修正的点当中不一定包含所有的common_tracks
            if len(output_mapping_node_id_to_belongings[node_id]) < 1:  # 可能和多个轨迹相似度都一样，可能两个点最小的轨迹相同
                # min_index = np.argwhere(np.array(node_track_mapping_matrix[fix_node_list.index(node_id),:]) == min(node_track_mapping_matrix[fix_node_list.index(node_id),:])).flatten()
                # # output_mapping_node_id_to_belongings[node_id] = list([common_tracks[np.argmin(node_track_mapping_matrix[fix_node_list.index(node_id),:])]]) # 只取最小的一个
                # output_mapping_node_id_to_belongings[node_id] = np.array(common_tracks)[min_index].tolist()
                output_mapping_node_id_to_belongings[node_id] = list([0])
            continue
        invalid_index = np.argwhere(np.array(node_track_mapping_matrix[fix_node_list.index(node_id),:])>100).flatten()#需要去掉的索引
        # invalid_index = np.where(np.array(node_track_mapping_matrix[fix_node_list.index(node_id),:])>100,1,0)[0] #需要去掉的索引 ??? 不对??
        output_mapping_node_id_to_belongings[node_id] = list(set(output_mapping_node_id_to_belongings[node_id])-set([common_tracks[x] for x in invalid_index if common_tracks[x] in output_mapping_node_id_to_belongings[node_id]])) # 需要修正的点当中不一定包含所有的common_tracks
        # ## 避免输出为空
        if len(output_mapping_node_id_to_belongings[node_id]) < 1:
        #     output_mapping_node_id_to_belongings[node_id] = random.choices(input_mapping_node_id_to_belongings[node_id], k=1)
            # output_mapping_node_id_to_belongings[node_id] = list([common_tracks[np.argmin(node_track_mapping_matrix[fix_node_list.index(node_id),:])]])
            min_index = np.argwhere(np.array(node_track_mapping_matrix[fix_node_list.index(node_id),:]) == min(node_track_mapping_matrix[fix_node_list.index(node_id),:])).flatten()
            output_mapping_node_id_to_belongings[node_id] = np.array(common_tracks)[min_index].tolist()


        #del output_mapping_node_id_to_belongings[node_id][invalid_index] # 保证不为空,因为可能最匹配的轨迹不在common_tracks当中
        # output_mapping_node_id_to_belongings[node_id] = list([common_tracks[np.argmin(node_track_mapping_matrix[fix_node_list.index(node_id),:])]]) # 可能该节点不属于任何轨迹但是强行匹配到,两个node最小的轨迹 id相同如何处理

    # 1 统计出该帧只可能属于单条轨迹的轨迹集合 2 其余大于1的情况下都得减去该集合的值然后将其转化为列表
    track_list = [x for x in predicted_tracks_centers]
    for frame_name in curr_batch_frame_node_list:
        curr_frame_node_list = curr_batch_frame_node_list[frame_name]
        track_set = set([output_mapping_node_id_to_belongings[node_id][0] for node_id in curr_frame_node_list if len(output_mapping_node_id_to_belongings[node_id])==1]) # output_mapping_node_id_to_belongings[node_id]为一个列表
        single_node_list = [node for node in curr_frame_node_list if len(output_mapping_node_id_to_belongings[node]) == 1]  # mapping唯一的点集合
        conflict_node = [(x,y) for x in single_node_list for y in single_node_list if x < y and output_mapping_node_id_to_belongings[x] == output_mapping_node_id_to_belongings[y] and output_mapping_node_id_to_belongings[x][0] != 0] # 保证唯一不重复
        fix_node = [node_id for node_id in curr_frame_node_list if len(output_mapping_node_id_to_belongings[node_id]) > 1] # node_key
        null_node = [node_id for node_id in curr_frame_node_list if len(output_mapping_node_id_to_belongings[node_id]) < 1] # 空的点
        for node_id in fix_node:
            output_mapping_node_id_to_belongings[node_id] = list(set(output_mapping_node_id_to_belongings[node_id])-track_set)
            if len(output_mapping_node_id_to_belongings[node_id]) < 1:
                possible_choice = list(set(track_list) - set(curr_frame_node_list))
                output_mapping_node_id_to_belongings[node_id] = random.choices(possible_choice,k=1) # 随机从未出现的轨迹中选择一个
        for node_id in null_node: # 来源于未配对的轨迹
            output_mapping_node_id_to_belongings[node_id] = list(set(input_mapping_node_id_to_belongings[node_id])-track_set)

        for conflict_pair in conflict_node:
            # 分情况讨论，如果都在 fix_node当中
            if conflict_pair[0] in fix_node_list and conflict_pair[1] in fix_node_list: # 找出当中node_mapping_更小的值
                if output_mapping_node_id_to_belongings[conflict_pair[0]][0] in common_tracks:
                    index = np.argwhere(node_track_mapping_matrix == min(node_track_mapping_matrix[fix_node_list.index(conflict_pair[0]),common_tracks.index(output_mapping_node_id_to_belongings[conflict_pair[0]][0])],node_track_mapping_matrix[fix_node_list.index(conflict_pair[1]),common_tracks.index(output_mapping_node_id_to_belongings[conflict_pair[1]][0])]))[0] # 表示行和列
                else: # 不在common_tracks则无法比较
                    continue
                if conflict_pair[0] == fix_node_list[index[0]]: # 对应的损失更小 ，可能对应的唯一轨迹不在common_tracks当中
                    output_mapping_node_id_to_belongings[conflict_pair[1]] = list(set(input_mapping_node_id_to_belongings[conflict_pair[1]])-track_set)
                else:
                    output_mapping_node_id_to_belongings[conflict_pair[0]] = list(set(input_mapping_node_id_to_belongings[conflict_pair[0]])-track_set)
                continue
            elif conflict_pair[0] in fix_node_list:
                output_mapping_node_id_to_belongings[conflict_pair[0]] = list(set(input_mapping_node_id_to_belongings[conflict_pair[0]])-track_set)
            elif conflict_pair[1] in fix_node_list:
                output_mapping_node_id_to_belongings[conflict_pair[1]] = list(set(input_mapping_node_id_to_belongings[conflict_pair[1]])-track_set)
                
            # output_mapping_node_id_to_belongings[conflict_pair[0]] = list(set(input_mapping_node_id_to_belongings[conflict_pair[0]])-track_set)
            # output_mapping_node_id_to_belongings[conflict_pair[1]] = list(set(input_mapping_node_id_to_belongings[conflict_pair[0]])-track_set)
    fixed_node_belongings = [output_mapping_node_id_to_belongings[x] for x in fix_node_list] # 需要修正的点修正之后的可能属于集合

    return output_mapping_node_id_to_belongings
        # traj_fit_error.append(
        #     np.polyfit(polyfit_x, polyfit_y, 1, full=True)[1][0] + np.polyfit(polyfit_x, polyfit_z, 1, full=True)[1][
        #         0])  # [1][0]表示拟合误差


def filter_out_invalid_combinations(input_each_frame_permutations, mapping_node_id_to_bbox, avoid_empty_result):
    # print('filter combination')
    iou_thresh = 0.8
    output_each_frame_permutations = copy.deepcopy(input_each_frame_permutations)
    output_each_frame_permutations[sorted([x for x in input_each_frame_permutations])[0]] = input_each_frame_permutations[sorted([x for x in input_each_frame_permutations])[0]]
    # x 表示frame name ‘352.jpg’

    for frame_key in sorted([x for x in input_each_frame_permutations])[1:]: # 遍历所有照片名
        if len(input_each_frame_permutations[frame_key]) == 1:
            output_each_frame_permutations[frame_key] = input_each_frame_permutations[frame_key]
        else:
            output_each_frame_permutations[frame_key] = []
            # for each candidate in previous frame, traverse all bboxes in curr frame, find if there's any bbox with over 0.8 iou but different id
            former_candidate_list = input_each_frame_permutations[sorted([x for x in input_each_frame_permutations])[sorted([x for x in input_each_frame_permutations]).index(frame_key) - 1]] # 前一帧候选顺序列表
            latter_candidate_list = input_each_frame_permutations[sorted([x for x in input_each_frame_permutations])[sorted([x for x in input_each_frame_permutations]).index(frame_key)]] # 当前帧候选顺序列表
            former_frame_key = sorted([x for x in input_each_frame_permutations])[sorted([x for x in input_each_frame_permutations]).index(frame_key) - 1] # 前一帧文件名
            former_frame_bbox_list = [mapping_node_id_to_bbox[x][0] for x in mapping_node_id_to_bbox if mapping_node_id_to_bbox[x][2] == former_frame_key] # 前一帧检测框
            latter_frame_bbox_list = [mapping_node_id_to_bbox[x][0] for x in mapping_node_id_to_bbox if mapping_node_id_to_bbox[x][2] == frame_key] # 当前帧检测框
            iou_matrix = compute_iou_between_bbox_list(latter_frame_bbox_list, former_frame_bbox_list) # 前一帧和当前帧list之间iou相似度
            inverse_iou_matrix = 1.0 - iou_matrix # 损失矩阵
            # avoid any row with two values > 0.8
            if inverse_iou_matrix.shape[0] > inverse_iou_matrix.shape[1]:
                add_width = inverse_iou_matrix.shape[0] - inverse_iou_matrix.shape[1]
                inverse_iou_matrix = np.concatenate((inverse_iou_matrix, np.ones((inverse_iou_matrix.shape[0], add_width)) * np.max(inverse_iou_matrix) * 2), axis=1)
                ot_src = [1.0] * inverse_iou_matrix.shape[0]
                ot_dst = [1.0] * inverse_iou_matrix.shape[1]
                iou_transportation_array = ot.emd(ot_src, ot_dst, inverse_iou_matrix)
                iou_transportation_array = iou_transportation_array[:, :iou_transportation_array.shape[1] - add_width]
            elif inverse_iou_matrix.shape[0] < inverse_iou_matrix.shape[1]:
                add_height = inverse_iou_matrix.shape[1] - inverse_iou_matrix.shape[0]
                inverse_iou_matrix = np.concatenate((inverse_iou_matrix, np.ones((add_height, inverse_iou_matrix.shape[1])) * np.max(inverse_iou_matrix) * 2), axis=0)
                ot_src = [1.0] * inverse_iou_matrix.shape[0]
                ot_dst = [1.0] * inverse_iou_matrix.shape[1]
                iou_transportation_array = ot.emd(ot_src, ot_dst, inverse_iou_matrix)
                iou_transportation_array = iou_transportation_array[:iou_transportation_array.shape[0] - add_height, :]
            else:
                ot_src = [1.0] * inverse_iou_matrix.shape[0]
                ot_dst = [1.0] * inverse_iou_matrix.shape[1]
                iou_transportation_array = ot.emd(ot_src, ot_dst, inverse_iou_matrix) # 匹配矩阵
            iou_matrix = np.multiply(iou_matrix, iou_transportation_array) # 对应元素位置相乘

            min_divergence_between_latter_with_previous = [] #保存每一个latter_candidate与former_candidate的冲突个数
            for latter_candidate in latter_candidate_list:
                whether_latter_contradictory_former = [] # 是否与前一帧冲突，冲突则值为冲突个数，否则为0
                for former_candidate in former_candidate_list:
                    # latter_candidate[np.where(iou_matrix > iou_thresh)[0][x]]：latter_candidate为iou_matrix当中的行
                    # np.where(iou_matrix > iou_thresh)[0]：行索引，np.where(iou_matrix > iou_thresh)[1]：列索引
                    if True in [latter_candidate[np.where(iou_matrix > iou_thresh)[0][x]] != former_candidate[np.where(iou_matrix > iou_thresh)[1][x]] for x in range(len(np.where(iou_matrix > iou_thresh)[0]))]: # x表示所有满足大于阈值检测框的索引 [2,5,3] [2,4,3]
                        whether_latter_contradictory_former.append([latter_candidate[np.where(iou_matrix > iou_thresh)[0][x]] != former_candidate[np.where(iou_matrix > iou_thresh)[1][x]] for x in range(len(np.where(iou_matrix > iou_thresh)[0]))].count(True)) # 统计True出现次数
                    else:
                        whether_latter_contradictory_former.append(0)
                if 0 in whether_latter_contradictory_former: # latter_candidate存在与former_candidate不冲突则添加进输出
                    output_each_frame_permutations[frame_key].append(latter_candidate)
                min_divergence_between_latter_with_previous.append(whether_latter_contradictory_former)
            # if all latter candidates are removed,避免输出为空
            if len(output_each_frame_permutations[frame_key]) == 0 and avoid_empty_result == 1:
                most_capable_candidate = latter_candidate_list[np.argmin([min(x) for x in min_divergence_between_latter_with_previous])] # 最有可能的latter candidate，latter candidate与former candidate最小值中取下标
                most_capable_candidate_corresponding_former_candidate = former_candidate_list[np.argmin(min_divergence_between_latter_with_previous[np.argmin([min(x) for x in min_divergence_between_latter_with_previous])])] # 最有可能的former candidate
                # 取所有存在矛盾的可能配对
                for coords in [[np.where(iou_matrix > iou_thresh)[0][x], np.where(iou_matrix > iou_thresh)[1][x]] for x in range(len(np.where(iou_matrix > iou_thresh)[0])) if (most_capable_candidate[np.where(iou_matrix > iou_thresh)[0][x]] != most_capable_candidate_corresponding_former_candidate[np.where(iou_matrix > iou_thresh)[1][x]])]: # 大于阈值当中所有后者和前者最有可能不匹配的行、列索引
                    if most_capable_candidate_corresponding_former_candidate[coords[1]] in most_capable_candidate:
                        # 根据前一帧中存在矛盾的在后一帧当中进行替换，eg：former = [5 4 3 2 1] latter = [ 4 5 3 2 1] 如果前一帧5(most_capable_candidate_corresponding_former_candidate[coords[1]])配对到当前帧4,则将当前帧的4变为5
                        most_capable_candidate = [most_capable_candidate[coords[0]] if x == most_capable_candidate_corresponding_former_candidate[coords[1]] else x for x in most_capable_candidate]
                        # most_capable_candidate.replace(most_capable_candidate_corresponding_former_candidate[coords[1]], most_capable_candidate[coords[0]])
                    most_capable_candidate[coords[0]] = most_capable_candidate_corresponding_former_candidate[coords[1]]
                output_each_frame_permutations[frame_key].append(most_capable_candidate)

            input_each_frame_permutations[frame_key] = output_each_frame_permutations[frame_key]
    return output_each_frame_permutations

def split_each_frame_permutations(each_frame_permutations, branch_frame_key,mapping_node_id_to_bbox):
    # 从最开始有多个分支时将each_frame_permutations进行分割
    num_groups = len(each_frame_permutations[branch_frame_key]) # 总共分成组数
    each_frame_permutations_candidates = []
    for idx_group in range(num_groups):
        each_frame_permutations_candidates.append({})
    for candidate_idx in range(num_groups):
        for instant in range(0, [x for x in each_frame_permutations].index(branch_frame_key)): # [x for x in each_frame_permutations]表示所有key，即frame name
            each_frame_permutations_candidates[candidate_idx][[x for x in each_frame_permutations][instant]] = \
            each_frame_permutations[[x for x in each_frame_permutations][instant]] # [x for x in each_frame_permutations][instant]:表示branch_frame_key之前的frame name
        each_frame_permutations_candidates[candidate_idx][branch_frame_key] = [each_frame_permutations[branch_frame_key][candidate_idx]]
        
        for instant in range([x for x in each_frame_permutations].index(branch_frame_key) + 1,len([x for x in each_frame_permutations])): # 遍历branch_frame_key之后的frame name
            each_frame_permutations_candidates[candidate_idx][[x for x in each_frame_permutations][instant]] = \
            each_frame_permutations[[x for x in each_frame_permutations][instant]]
            # ### 对frame_key 进行操作 ### 如果存在一帧当中没有多余的情况则选取
            # if len([x for x in each_frame_permutations[[x for x in each_frame_permutations][instant]] if len(x) == len(np.unique(x).tolist())]) >= 1:
            #     each_frame_permutations_candidates[candidate_idx][[x for x in each_frame_permutations][instant]] = \
            #         [x for x in each_frame_permutations[[x for x in each_frame_permutations][instant]] if len(x) == len(np.unique(x).tolist())]

        # each_frame_permutations_candidates[candidate_idx] = filter_out_invalid_combinations(each_frame_permutations_candidates[candidate_idx], mapping_node_id_to_bbox, 1)

    return each_frame_permutations_candidates


def BO_fix_Thompson_sampling(result, mapping_edge_id_to_cost, mapping_node_id_to_bbox, mapping_node_id_to_features, device, source):
    # initialize parameters for BO
    n_init = 20 # 最初采样点个数
    max_evals = 200 # BO采样最长步数
    batch_size = int(int(max_evals - n_init) / 2)# int(int(max_evals - n_init) / 2) # 90
    assert(n_init < max_evals)
    seed = 0  # To get the same Sobol points
    dim, data_dimension = 10, 10
    shared_args = {
        "n_init": n_init,
        "max_evals": max_evals,
        "batch_size": batch_size,
        "seed": seed,
    }
    SMOKE_TEST = os.environ.get("SMOKE_TEST")
    pykeops.test_torch_bindings()
    USE_KEOPS = True if not SMOKE_TEST else False
    N_CAND = 50000 if not SMOKE_TEST else 10
    N_CAND_CHOL = 10000 if not SMOKE_TEST else 10
    dtype = torch.float
    # x表示key mapping_node_id_to_bbox[x][2]:frame name  frame list:unique frame name list
    frame_list = np.unique([mapping_node_id_to_bbox[x][2] for x in mapping_node_id_to_bbox]) # potential bug no sort

    # we only revise result instead of adding any node to it
    # split_each_track:每条轨迹所包含的节点连接顺序，split_each_track_valid_mask:不正确的点标注为-1,不正确的边标注为0,正确结果标注为１
    split_each_track, split_each_track_valid_mask = update_split_each_track_valid_mask(result)

    # dst_path = '/home/allenyljiang/Documents/Dataset/MOT16/train/MOT16-02/ssp.txt'
    # dst_write = open(dst_path,'w')
    # dst_write.write(json.dumps(split_each_track))
    # dst_write.close()
    # collect invalid nodes and edges, then determine possible traj belongings of each node in mapping_node_id_to_bbox
    mapping_node_id_to_belongings = {} #每一个节点可能属于的轨迹集合
    for mapping_node_id_to_bbox_id in mapping_node_id_to_bbox:
        mapping_node_id_to_belongings[mapping_node_id_to_bbox_id] = []
    for split_each_track_valid_mask_id in split_each_track_valid_mask:
        if (0 in split_each_track_valid_mask[split_each_track_valid_mask_id]) or (-1 in split_each_track_valid_mask[split_each_track_valid_mask_id]):# 表示该条轨迹有异常结果
            invalid_segments_starts = [(instant + 1) for instant in range(len(split_each_track_valid_mask[split_each_track_valid_mask_id]) - 1) if (split_each_track_valid_mask[split_each_track_valid_mask_id][instant] == 1 and split_each_track_valid_mask[split_each_track_valid_mask_id][instant + 1] <= 0)] + ([0] if split_each_track_valid_mask[split_each_track_valid_mask_id][0] <= 0 else []) #

            other_traj_correlated_to_curr_traj = [split_each_track_valid_mask_id] # 包含[curr_invalid_segments_start,curr_invalid_segments_end]内点的其他轨迹
            for curr_invalid_segments_start in invalid_segments_starts: #　对于每一个curr_invalid_segments_start计算其终点curr_invalid_segments_end
                curr_invalid_segments_end= len(split_each_track_valid_mask[split_each_track_valid_mask_id]) - 1 #从curr_invalid_segments_start开始向后的所有都有可能出错
                if len([x for x in range(curr_invalid_segments_start, len(split_each_track_valid_mask[split_each_track_valid_mask_id]) - 1) if split_each_track_valid_mask[split_each_track_valid_mask_id][x + 1] == 1]) > 0:
                    curr_invalid_segments_end = [x for x in range(curr_invalid_segments_start, len(split_each_track_valid_mask[split_each_track_valid_mask_id]) - 1) if split_each_track_valid_mask[split_each_track_valid_mask_id][x + 1] == 1][0] # 对segment终点修正
                for invalid_node in [split_each_track[split_each_track_valid_mask_id][x] for x in range(curr_invalid_segments_start, curr_invalid_segments_end + 1)]:
                    other_traj_correlated_to_curr_traj += [split_each_track_valid_mask_other_id for split_each_track_valid_mask_other_id in [x for x in split_each_track_valid_mask if x != split_each_track_valid_mask_id] if (invalid_node in split_each_track[split_each_track_valid_mask_other_id] or [invalid_node[1], invalid_node[0]] in split_each_track[split_each_track_valid_mask_other_id])] # split_each_track_valid_mask_other_id:包含invalid node的其他轨迹
            other_traj_correlated_to_curr_traj = np.unique(other_traj_correlated_to_curr_traj).tolist()

            for curr_invalid_segments_start in invalid_segments_starts:
                curr_invalid_segments_end = len(split_each_track_valid_mask[split_each_track_valid_mask_id]) - 1
                if len([x for x in range(curr_invalid_segments_start, len(split_each_track_valid_mask[split_each_track_valid_mask_id]) - 1) if split_each_track_valid_mask[split_each_track_valid_mask_id][x + 1] == 1]) > 0:
                    curr_invalid_segments_end = [x for x in range(curr_invalid_segments_start, len(split_each_track_valid_mask[split_each_track_valid_mask_id]) - 1) if split_each_track_valid_mask[split_each_track_valid_mask_id][x + 1] == 1][0] # 对segment终点修正
                for invalid_node in [split_each_track[split_each_track_valid_mask_id][x] for x in range(curr_invalid_segments_start, curr_invalid_segments_end + 1)]: # 遍历该条轨迹的invalid_node
                    for split_each_track_valid_mask_other_id in [split_each_track_valid_mask_other_id for split_each_track_valid_mask_other_id in [x for x in split_each_track_valid_mask if x != split_each_track_valid_mask_id] if (invalid_node in split_each_track[split_each_track_valid_mask_other_id] or [invalid_node[1], invalid_node[0]] in split_each_track[split_each_track_valid_mask_other_id])]:
                         # 其余的track　id（包含该无效边或其相反边）
                        allocation_start_idx = split_each_track[split_each_track_valid_mask_other_id].index(invalid_node if invalid_node in split_each_track[split_each_track_valid_mask_other_id] else [invalid_node[1], invalid_node[0]]) # 其余轨迹中invalid_node的开始位置
                        for other_to_this_idx in [x for x in range(allocation_start_idx, len(split_each_track_valid_mask[split_each_track_valid_mask_other_id])) if (split_each_track_valid_mask[split_each_track_valid_mask_other_id][x] == 1 and int(split_each_track[split_each_track_valid_mask_other_id][x][0]) % 2 == 1 and int(split_each_track[split_each_track_valid_mask_other_id][x][1]) % 2 == 0)]: #其余轨迹从无效边到最后所有表示人的edge
                            mapping_node_id_to_belongings[int(int(split_each_track[split_each_track_valid_mask_other_id][other_to_this_idx][1]) / 2)] += other_traj_correlated_to_curr_traj #.append(split_each_track_valid_mask_id)
                    curr_invalid_node_shared_by_other_traj_list = [split_each_track_valid_mask_other_id for split_each_track_valid_mask_other_id in [x for x in split_each_track_valid_mask if x != split_each_track_valid_mask_id] if (invalid_node in split_each_track[split_each_track_valid_mask_other_id] or [invalid_node[1], invalid_node[0]] in split_each_track[split_each_track_valid_mask_other_id])]
                    # 包含当前invalide node 的所有其他轨迹list
                    for later_node_idx in [x for x in range(split_each_track[split_each_track_valid_mask_id].index(invalid_node), len(split_each_track[split_each_track_valid_mask_id])) if (x % 2 == 0 and split_each_track_valid_mask[split_each_track_valid_mask_id][x] == 1)]: #当前轨迹invalid_node之后表示人的edge并且mask=1
                        mapping_node_id_to_belongings[int(int(split_each_track[split_each_track_valid_mask_id][later_node_idx][1]) / 2)] += curr_invalid_node_shared_by_other_traj_list
    for split_each_track_valid_mask_id in split_each_track_valid_mask: # 对于其余时刻mask正确的情况,belongings唯一
        for instant in [x for x in range(len(split_each_track_valid_mask[split_each_track_valid_mask_id])) if (x % 2 == 0 and split_each_track_valid_mask[split_each_track_valid_mask_id][x] == 1)]:# ???
            mapping_node_id_to_belongings[int(int(split_each_track[split_each_track_valid_mask_id][instant][1]) / 2)].append(split_each_track_valid_mask_id)
    # 对mapping_node_id_to_belongings进行简化
    curr_batch_frame_node_list = {}  # dict,包含每帧包含节点id
    for frame_name in frame_list:
        curr_batch_frame_node_list[frame_name] = [x for x in mapping_node_id_to_bbox if mapping_node_id_to_bbox[x][2] == frame_name]

    predicted_tracks_centers,predicted_tracks_bboxes,predicted_tracks_bboxes_test = convert_track_to_bbox_list(split_each_track, mapping_node_id_to_bbox,mapping_node_id_to_belongings)


    start = time.time()
    for mapping_node_id_to_bbox_id in mapping_node_id_to_bbox:
        mapping_node_id_to_belongings[mapping_node_id_to_bbox_id] = np.unique(mapping_node_id_to_belongings[mapping_node_id_to_bbox_id]).tolist()

    input_mapping_node_id_to_belongings = copy.deepcopy(mapping_node_id_to_belongings)
    mapping_node_id_to_belongings = filter_out_invalid_mapping_node_id_to_belonglings(input_mapping_node_id_to_belongings, mapping_node_id_to_bbox,
                                                          predicted_tracks_centers, predicted_tracks_bboxes,curr_batch_frame_node_list)
    end = time.time()
    print('filter belongings time: '+str(end-start))
    # 使得belongings按照升序并且唯一排布
    for mapping_node_id_to_bbox_id in mapping_node_id_to_bbox:
        mapping_node_id_to_belongings[mapping_node_id_to_bbox_id] = np.unique(mapping_node_id_to_belongings[mapping_node_id_to_bbox_id]).tolist()
    # build permutations in all frames

    each_frame_permutations = {} # 返回每帧可能的节点排列顺序（从左到右）
    each_frame_permutations_backup = {}
    for frame_name in frame_list:# 为什么返回的each_frame_permutations可能为空???
        # curr_frame_node_list = [x for x in mapping_node_id_to_bbox if mapping_node_id_to_bbox[x][2] == frame_name] #　当前帧的节点list,存在冲突
        curr_frame_node_list = curr_batch_frame_node_list[frame_name]
        each_frame_permutations[frame_name] = [0] * np.prod([len(mapping_node_id_to_belongings[x]) for x in curr_frame_node_list]) # np.prod:给定维数乘
        for permutation_idx in range(len(each_frame_permutations[frame_name])): # permutation_idx为each_frame_permutations的索引id
            each_frame_permutations[frame_name][permutation_idx] = []
            permutation_idx_tmp = copy.deepcopy(permutation_idx)
            for curr_frame_node in curr_frame_node_list:
                each_frame_permutations[frame_name][permutation_idx].append(mapping_node_id_to_belongings[curr_frame_node][int(permutation_idx_tmp / np.prod([len(mapping_node_id_to_belongings[curr_frame_node_list[y]]) for y in range(curr_frame_node_list.index(curr_frame_node) + 1, len(curr_frame_node_list))]))])
                permutation_idx_tmp = permutation_idx_tmp % np.prod([len(mapping_node_id_to_belongings[curr_frame_node_list[y]]) for y in range(curr_frame_node_list.index(curr_frame_node) + 1, len(curr_frame_node_list))])
        # each_frame_permutations[frame_name] = [x for x in each_frame_permutations[frame_name] if len(x) == len(np.unique(x).tolist())] # frame_permutations当中有重复元素出现
        # 根据当前帧检测到的数目与总的轨迹数进行比较
        each_frame_permutations_backup[frame_name] = [x for x in each_frame_permutations[frame_name]]
        each_frame_permutations[frame_name] = [x for x in each_frame_permutations[frame_name] if len(x) <= len(np.unique(x).tolist())+1+abs(len(predicted_tracks_centers)-len(curr_frame_node_list))] # frame_permutations当中有重复元素出现???
        # if len([x for x in each_frame_permutations[frame_name] if len(x) == len(np.unique(x).tolist())]) >= 1: # 如果存在都不相等的组合
        #     each_frame_permutations[frame_name] = [x for x in each_frame_permutations[frame_name] if len(x) == len(np.unique(x).tolist())]
        if each_frame_permutations[frame_name] == []:
            each_frame_permutations[frame_name] = each_frame_permutations_backup[frame_name]

    # # 清除掉不用的字典
    # mapping_node_id_to_belongings.clear()
    # curr_batch_frame_node_list.clear()
    # filter out invalid permutation
    # for frame_key in sorted([x for x in each_frame_permutations]):
    #     if len(each_frame_permutations[frame_key]) == 1:
    #         continue
    #     for idx,frame_permutation in enumerate(each_frame_permutations[frame_key]):
    #         if len(set(frame_permutation)) <= len(frame_permutation)-2:
    #             each_frame_permutations[frame_key].pop(idx)


    # each_frame_permutations = filter_out_invalid_combinations(each_frame_permutations, mapping_node_id_to_bbox, 1) # 去除不可能的排列组合，减少搜索空间

    # divide each_frame_permutations into channel-wise
    each_frame_permutations_candidates = [] # 缩小搜索空间之后的结果
    if max([len(each_frame_permutations[x]) for x in each_frame_permutations][:-1]) == 1: # ???
        each_frame_permutations_candidates.append(each_frame_permutations)
    else: # there must be an element in each_frame_permutations with length > 1
        for branch_frame_key in [x for x in each_frame_permutations if len(each_frame_permutations[x]) > 1]:
            each_frame_permutations_candidates = split_each_frame_permutations(each_frame_permutations, branch_frame_key,mapping_node_id_to_bbox)
            
            if np.sum([np.prod([len(x[y]) for y in x]) for x in each_frame_permutations_candidates]) < np.prod([len(each_frame_permutations[y]) for y in each_frame_permutations]):
                break

    # each_frame_permutation_candidate当中可能会有重复的
    num_people_each_frame_list = [len([y for y in mapping_node_id_to_bbox if mapping_node_id_to_bbox[y][2] == x]) for x in frame_list]
    all_people_visible_frame = frame_list[random.choice(np.where(np.array(num_people_each_frame_list) == max(num_people_each_frame_list))[0])] # np.where返回值为元组,[0]为列表，此处随机返回一个值
    unique_id_features = [mapping_node_id_to_features[x] for x in mapping_node_id_to_bbox if mapping_node_id_to_bbox[x][2] == all_people_visible_frame]
    unique_id_list = [1 + x for x in range(max(num_people_each_frame_list))] # id 标识，所有u可能的轨迹
    assert (len(frame_list) == data_dimension and len(num_people_each_frame_list) == data_dimension)


    # Some branches in each_frame_permutations_candidates may have no offsprings, for instance:
    # {'012.jpg': [[1, 3, 2]], '013.jpg': [[3, 1, 2]], '014.jpg': [[3, 1, 2]], '015.jpg': [[5, 2, 1]], '016.jpg': [], '017.jpg': [], '018.jpg': [], '019.jpg': [], '020.jpg': [], '021.jpg': []}
    # IN this case, the branch should be removed
    valid_part_of_each_frame_permutations_candidates = []
    for each_frame_permutations_candidates_single_branch in each_frame_permutations_candidates:
        if 0 not in [len(each_frame_permutations_candidates_single_branch[x]) for x in each_frame_permutations_candidates_single_branch]:
            valid_part_of_each_frame_permutations_candidates.append(each_frame_permutations_candidates_single_branch)
    each_frame_permutations_candidates = valid_part_of_each_frame_permutations_candidates

    # define functions
    def eval_objective(input_tensor):
        # 目标函数　f(x)，输入为ｘ
        overall_loss = 0.0 #表示相似度，可以对损失函数进行修改，ssp只用外观相似度
        batch_humans_cluster = {} # 表示人编号的节点序列
        for unique_id in unique_id_list:
            batch_humans_cluster[unique_id] = [] # 清空batch_humans_cluster
        for frame_idx in range(int(data_dimension)):
            frame_name = frame_list[frame_idx]
            unique_id_order_list = each_frame_permutations[frame_name][int(len(each_frame_permutations[frame_name]) * min([input_tensor[frame_idx].item(), 0.99]))] # 当前x对应的id list.即该帧从左到右的排列
            for bbox_id_left2right_list_item in list(unique_id_order_list): # bbox_id_left2right_list_item表示node_id
                batch_humans_cluster[bbox_id_left2right_list_item].append([x for x in mapping_node_id_to_bbox if mapping_node_id_to_bbox[x][2] == frame_name][list(unique_id_order_list).index(bbox_id_left2right_list_item)])
                # [x for x in mapping_node_id_to_bbox if mapping_node_id_to_bbox[x][2] == frame_name]表示该帧的所有节点node_id
                # [list(unique_id_order_list).index(bbox_id_left2right_list_item)]:表示
            # if any of current frame's bbox has iou>0.8 with previous bbox but with different id, return 0
        traj_fit_error = []

        for unique_id in unique_id_list:
            batch_humans_cluster[unique_id] = sorted(batch_humans_cluster[unique_id])
            polyfit_x, polyfit_y, polyfit_z = [], [], [] # 利用多项式拟合判断轨迹的连续性
            for instant in range(len(batch_humans_cluster[unique_id]) - 1): # instant表示时刻 # if abs(np.linalg.norm(curr_id_mean) - np.linalg.norm(curr_id_vector)) != 0:
                if abs(int(mapping_node_id_to_bbox[batch_humans_cluster[unique_id][instant]][2].split('.')[0]) - int(mapping_node_id_to_bbox[batch_humans_cluster[unique_id][instant + 1]][2].split('.')[0])) <= 1: # 判断出现的当前instant和下一个instant是否在一张图片内
                    former_vector = mapping_node_id_to_features[batch_humans_cluster[unique_id][instant]]
                    latter_vector = mapping_node_id_to_features[batch_humans_cluster[unique_id][instant + 1]]
                    former_bbox = mapping_node_id_to_bbox[batch_humans_cluster[unique_id][instant]][0]
                    latter_bbox = mapping_node_id_to_bbox[batch_humans_cluster[unique_id][instant + 1]][0]
                    overall_loss += (np.array(former_vector).dot(np.array(latter_vector)) / (np.linalg.norm(former_vector) * np.linalg.norm(latter_vector)) + compute_iou_single_box([former_bbox[0][1], former_bbox[1][1], former_bbox[0][0], former_bbox[1][0]], [latter_bbox[0][1], latter_bbox[1][1], latter_bbox[0][0], latter_bbox[1][0]]) - 0.5)
                else:
                    former_vector = mapping_node_id_to_features[batch_humans_cluster[unique_id][instant]]
                    latter_vector = mapping_node_id_to_features[batch_humans_cluster[unique_id][instant + 1]]
                    former_bbox = mapping_node_id_to_bbox[batch_humans_cluster[unique_id][instant]][0]
                    latter_bbox = mapping_node_id_to_bbox[batch_humans_cluster[unique_id][instant + 1]][0]
                    overall_loss += np.array(former_vector).dot(np.array(latter_vector)) / (np.linalg.norm(former_vector) * np.linalg.norm(latter_vector)) #/ abs(np.linalg.norm(former_vector) - np.linalg.norm(latter_vector))
                polyfit_x.append(instant) # 所有时刻列表
                polyfit_y.append((former_bbox[0][1] + former_bbox[1][1]) / 2) # 所有时刻y轴中心点
                polyfit_z.append((former_bbox[0][0] + former_bbox[1][0]) / 2) # 所有时刻x轴中心点
                if instant == len(batch_humans_cluster[unique_id]) - 2:
                    polyfit_x.append(instant + 1)
                    polyfit_y.append((latter_bbox[0][1] + latter_bbox[1][1]) / 2)
                    polyfit_z.append((latter_bbox[0][0] + latter_bbox[1][0]) / 2)
            if len(polyfit_x) > 2:
                traj_fit_error.append(np.polyfit(polyfit_x, polyfit_y, 1, full=True)[1][0] + np.polyfit(polyfit_x, polyfit_z, 1, full=True)[1][0])# [1][0]表示拟合误差
        if len(traj_fit_error) > 0:
            return overall_loss / len([x for x in batch_humans_cluster if len(batch_humans_cluster[x]) > 1]) / (np.mean(traj_fit_error)) if len([x for x in batch_humans_cluster if len(batch_humans_cluster[x]) > 1]) != 0 else overall_loss / (np.mean(traj_fit_error)) #/ np.sum([len(batch_humans_cluster[x]) for x in batch_humans_cluster])
        return overall_loss / len([x for x in batch_humans_cluster if len(batch_humans_cluster[x]) > 1]) if len([x for x in batch_humans_cluster if len(batch_humans_cluster[x]) > 1]) != 0 else overall_loss

    def get_initial_points(dim, n_pts, seed=None):
        sobol = SobolEngine(dimension=dim, scramble=True, seed=seed)
        X_init = sobol.draw(n=n_pts).to(dtype=dtype, device=device)
        return X_init

    def generate_batch(
            X,
            Y,
            batch_size,
            n_candidates,
            sampler="ciq",  # "cholesky", "ciq", "rff"　
            use_keops=False,
    ):
        assert sampler in ("cholesky", "ciq", "rff", "lanczos")    # 出现错误条件时抛出AssertionError错误
        assert X.min() >= 0.0 and X.max() <= 1.0 and torch.all(torch.isfinite(Y))

        # NOTE: We probably want to pass in the default priors in SingleTaskGP here later
        kernel_kwargs = {"nu": 2.5, "ard_num_dims": X.shape[-1]}   # X.shape[-1] = 10 ???
        if sampler == "rff":
            base_kernel = RFFKernel(**kernel_kwargs, num_samples=1024)
        else:
            base_kernel = (
                KMaternKernel(**kernel_kwargs) if use_keops else MaternKernel(**kernel_kwargs)
            )
        covar_module = ScaleKernel(base_kernel)

        # Fit a GP model
        train_Y = (Y - Y.mean()) / Y.std()
        likelihood = GaussianLikelihood(noise_constraint=Interval(1e-8, 1e-3))
        model = SingleTaskGP(X, train_Y, likelihood=likelihood, covar_module=covar_module)   # SingleTaskGP　使用相同的训练数据并且输出独立
        mll = ExactMarginalLogLikelihood(model.likelihood, model) # 计算边缘对数似然mll,常用于GP模型损失函数
        fit_gpytorch_model(mll)

        # Draw samples on a Sobol sequence
        sobol = SobolEngine(X.shape[-1], scramble=True) # X.shape[-1]序列维数
        X_cand = sobol.draw(n_candidates).to(dtype=dtype, device=device) # (n_candidates,dimension)

        # Thompson sample
        with ExitStack() as es:
            if sampler == "cholesky":
                es.enter_context(gpts.max_cholesky_size(float("inf")))
            elif sampler == "ciq":
                es.enter_context(gpts.fast_computations(covar_root_decomposition=True))
                es.enter_context(gpts.max_cholesky_size(0))
                es.enter_context(gpts.ciq_samples(True))
                es.enter_context(gpts.minres_tolerance(2e-3))  # Controls accuracy and runtime
                es.enter_context(gpts.num_contour_quadrature(15))
            elif sampler == "lanczos":
                es.enter_context(gpts.fast_computations(covar_root_decomposition=True))
                es.enter_context(gpts.max_cholesky_size(0))
                es.enter_context(gpts.ciq_samples(False))
            elif sampler == "rff":
                es.enter_context(gpts.fast_computations(covar_root_decomposition=True))

            thompson_sampling = MaxPosteriorSampling(model=model, replacement=False)
            X_next = thompson_sampling(X_cand, num_samples=batch_size)

        return X_next

    def run_optimization(sampler, n_candidates, n_init, max_evals, batch_size, use_keops=False, seed=None):
        # 通过 TS 来减少搜索空间
        init_start_time = time.time()
        X = get_initial_points(dim, n_init, seed) # 20*10 每个数取值０～１最终映射到可能的轨迹
        Y = torch.tensor([eval_objective(x) for x in X], dtype=dtype, device=device).unsqueeze(-1) # f(X)=eval_objective 重点修改,unsqueeze(-1):添加最后一维
        init_end_time = time.time()
        # train_Y = (train_Y - min(train_Y)) / (max(train_Y) - min(train_Y))
        # print(f"{len(X)}) Best value: {Y.max().item():.2e}")
        tmp_X = X[torch.argmax(Y),:]
        tmp_Y = Y.max()
        SSP_objective_value = Y.max().item() # 将tensor标量转化为python标量,转化过后dtype一致

        while len(X) < max_evals:# 采样点数目小于max_evals，两次X_next加进来
            # Create a batch
            start = time.time()
            X_next = generate_batch( # 产生下一个采样点
                X=X,
                Y=Y,
                batch_size=min(batch_size, max_evals - len(X)),
                n_candidates=n_candidates,
                sampler=sampler,
                use_keops=use_keops,
            )
            end = time.time()
            # print(f"Generated batch in {end - start:.1f} seconds")
            Y_next = torch.tensor(
                [eval_objective(x) for x in X_next], dtype=dtype, device=device
            ).unsqueeze(-1)
            endend = time.time()
            # Append data
            X = torch.cat((X, X_next), dim=0)
            Y = torch.cat((Y, Y_next), dim=0)

        # print(f"{len(X)}) Best value: {Y.max().item():.2e}")
        if torch.max(Y).item() > SSP_objective_value:# Problem: if max value shared by multiple choices
            return X[torch.argmax(Y).item(), :], Y[torch.argmax(Y).item(), :]
        return tmp_X, tmp_Y

    # X_chol, Y_chol = run_optimization("ciq", N_CAND_CHOL, **shared_args)


    X_chol_list, Y_chol_list = [], [] # list长度与len(each_frame_permutations_candidates)相同
    for each_frame_permutations_candidates_idx in range(len(each_frame_permutations_candidates)):
        each_frame_permutations = each_frame_permutations_candidates[each_frame_permutations_candidates_idx]
        # if only one possibility, do not optimize
        if max([len(each_frame_permutations[x]) for x in each_frame_permutations]) == 1:
            X_chol_list.append(torch.tensor(np.array([0.5] * dim)))
            Y_chol_list.append(eval_objective(torch.tensor(np.array([0.5] * dim))))
        else:
            if np.prod([len(each_frame_permutations[x]) for x in each_frame_permutations]) <= max_evals: # 小于max_evals时候采用遍历
                logit_combinations = [[(each_frame_permutations[x].index(y)) / len(each_frame_permutations[x]) + 1 / len(each_frame_permutations[x]) / 2 for y in each_frame_permutations[x]] for x in each_frame_permutations] # x:frame name　logit_combinations:为每一种可能分配一个0~1之间的数
                permutation_candidates = list(itertools.product(logit_combinations[0], logit_combinations[1], logit_combinations[2], logit_combinations[3], logit_combinations[4], logit_combinations[5], logit_combinations[6], logit_combinations[7], logit_combinations[8], logit_combinations[9], repeat = 1)) # itertools.product以元组的形式，根据输入的可遍历对象生成笛卡尔积，repeat = 1可以不加
                eval_results = [eval_objective(torch.tensor(np.array(permutation_candidate))) for permutation_candidate in permutation_candidates]
                max_candidate_id = np.argmax(eval_results)
                X_chol, Y_chol = torch.tensor(np.array(permutation_candidates[max_candidate_id])), torch.tensor(np.array(np.max(eval_results)))
            else:
                X_chol, Y_chol = run_optimization("ciq", N_CAND_CHOL, **shared_args) # ciq　进行TS采样优化
            X_chol_list.append(X_chol)
            Y_chol_list.append(Y_chol.cpu().numpy())
    X_chol = X_chol_list[np.argmax(Y_chol_list)]

    optimal_10D_vector = X_chol.cpu().numpy()#[-5:][np.argmax(Y_chol.cpu().numpy()[-5:])]

    each_frame_permutations = each_frame_permutations_candidates[np.argmax(Y_chol_list)]
    # each_frame_permutations = each_frame_permutations_candidates[0]
    # draw the results of BO
    split_each_track_refined = {} # 每条轨迹包含的节点顺序
    for frame_idx in range(int(data_dimension)):
        frame_name = frame_list[frame_idx]
        # 每一帧从左到右的顺序
        unique_id_order_list = each_frame_permutations[frame_name][int(len(each_frame_permutations[frame_name]) * optimal_10D_vector[frame_idx].item())] # optimal_10D_vector将X映射为顺序列表

        for unique_id_order_list_item in unique_id_order_list:
            if unique_id_order_list_item not in split_each_track_refined:
                split_each_track_refined[unique_id_order_list_item] = []
            node_to_add = [x for x in mapping_node_id_to_bbox if mapping_node_id_to_bbox[x][2] == frame_list[frame_idx]][unique_id_order_list.index(unique_id_order_list_item)]
            # split_each_track_refined  表示每一条轨迹
            split_each_track_refined[unique_id_order_list_item].append([str(2*node_to_add-1), str(2*node_to_add)])
    for split_each_track_refined_key in split_each_track_refined:
        split_each_track_refined[split_each_track_refined_key] = interpolate_to_obtain_traj(split_each_track_refined[split_each_track_refined_key]) # 插入节点之间的连边形成轨迹
    del split_each_track_refined[0]
    result[0] = 'Predicted tracks' + '\n' + convert_dict_to_str(result, split_each_track_refined)
    return result

def evaluate_similarity(split_each_track_refined, mapping_node_id_to_features):
    overall_loss = 0.0
    for split_each_track_refined_key in split_each_track_refined:
        for instant in range(0, len(split_each_track_refined[split_each_track_refined_key]) - 2, 2):
            former_vector = mapping_node_id_to_features[int(int(split_each_track_refined[split_each_track_refined_key][instant][1]) / 2)]
            latter_vector = mapping_node_id_to_features[int(int(split_each_track_refined[split_each_track_refined_key][instant + 2][1]) / 2)]
            overall_loss += np.array(former_vector).dot(np.array(latter_vector)) / (np.linalg.norm(former_vector) * np.linalg.norm(latter_vector)) / abs(np.linalg.norm(former_vector) - np.linalg.norm(latter_vector))
    return overall_loss

def BO_fix_trajs(result, mapping_edge_id_to_cost, mapping_node_id_to_bbox, mapping_node_id_to_features):
    # encode id orders
    data_dimension = 20
    train_X = torch.rand(100, data_dimension)
    train_Y = torch.zeros(100, 1)
    # map 20-dim data to trajectories
    frame_list = np.unique([mapping_node_id_to_bbox[x][2] for x in mapping_node_id_to_bbox])
    num_people_each_frame_list = [len([y for y in mapping_node_id_to_bbox if mapping_node_id_to_bbox[y][2]==x]) for x in frame_list]
    all_people_visible_frame = frame_list[random.choice(np.where(np.array(num_people_each_frame_list) == max(num_people_each_frame_list))[0])]
    unique_id_features = [mapping_node_id_to_features[x] for x in mapping_node_id_to_bbox if mapping_node_id_to_bbox[x][2] == all_people_visible_frame]
    unique_id_list = [1 + x for x in range(max(num_people_each_frame_list))]
    assert(len(frame_list) == data_dimension / 2 and len(num_people_each_frame_list) == data_dimension / 2)
    for sample_idx in range(train_X.shape[0]):
        overall_loss = 0.0
        for frame_idx in range(int(data_dimension / 2)):
            num_people_curr_frame = num_people_each_frame_list[frame_idx]
            visibility_binary = np.array([0] * len(unique_id_list))
            visibility_binary[:num_people_curr_frame] = 1
            visibility_max_value = binary2int(visibility_binary)
            all_permutations = list(set(list(permutations([x for x in visibility_binary.tolist()]))))
            all_permutations.sort(key=lambda x: binary2int(x))
            unique_id_visibility_list = all_permutations[min([int(len(all_permutations) * train_X[sample_idx, frame_idx + int(data_dimension / 2)].item()), len(all_permutations) - 1])]
            # visibility_actual_value = int(round(visibility_max_value * train_X[sample_idx, frame_idx + int(data_dimension / 2)].item()))
            # visibility_list = lambda x, n: format(x, 'b').zfill(n)
            # unique_id_visibility_list = [x for x in str(visibility_list(visibility_actual_value, len(unique_id_list)))]
            all_permutations = list(set(list(permutations([x for x in unique_id_list]))))
            all_permutations.sort(key=lambda x: decimal2int(x))
            unique_id_order_list = all_permutations[min([int(len(all_permutations) * train_X[sample_idx, frame_idx].item()), len(all_permutations) - 1])]

            bbox_id_left2right_list = [unique_id_order_list[x] for x in range(len(unique_id_visibility_list)) if unique_id_visibility_list[x] > 0]
            curr_frame_bbox_features = {}
            frame_name = frame_list[frame_idx]
            for bbox_id_left2right_list_item in bbox_id_left2right_list:
                curr_frame_bbox_features[bbox_id_left2right_list_item] = [mapping_node_id_to_features[y] for y in mapping_node_id_to_features if y in [x for x in mapping_node_id_to_bbox if mapping_node_id_to_bbox[x][2]==frame_name]][bbox_id_left2right_list.index(bbox_id_left2right_list_item)]
                overall_loss += 1.0 - compute_reid_vector_distance(unique_id_features[unique_id_list.index(bbox_id_left2right_list_item)], curr_frame_bbox_features[bbox_id_left2right_list_item])
        train_Y[sample_idx, 0] = overall_loss
    train_Y = (train_Y - min(train_Y)) / (max(train_Y) - min(train_Y))
    # BO
    gp = SingleTaskGP(train_X, train_Y)
    mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
    fit_gpytorch_model(mll)
    UCB = UpperConfidenceBound(gp, beta=0.1)
    bounds = torch.stack([torch.zeros(data_dimension), torch.ones(data_dimension)])
    start_time = time.time()
    candidate, acq_value = optimize_acqf(
        UCB, bounds=bounds, q=1, num_restarts=100, raw_samples=100,
    )
    end_time = time.time()

    # draw the results of BO
    for frame_idx in range(int(data_dimension / 2)):
        num_people_curr_frame = num_people_each_frame_list[frame_idx]
        visibility_binary = np.array([0] * len(unique_id_list))
        visibility_binary[:num_people_curr_frame] = 1
        visibility_max_value = binary2int(visibility_binary)
        all_permutations = list(set(list(permutations([x for x in visibility_binary.tolist()]))))
        all_permutations.sort(key=lambda x: binary2int(x))
        unique_id_visibility_list = all_permutations[min([int(len(all_permutations) * candidate[0, frame_idx + int(data_dimension / 2)].item()), len(all_permutations) - 1])]
        # visibility_actual_value = int(round(visibility_max_value * train_X[sample_idx, frame_idx + int(data_dimension / 2)].item()))
        # visibility_list = lambda x, n: format(x, 'b').zfill(n)
        # unique_id_visibility_list = [x for x in str(visibility_list(visibility_actual_value, len(unique_id_list)))]
        all_permutations = list(set(list(permutations([x for x in unique_id_list]))))
        all_permutations.sort(key=lambda x: decimal2int(x))
        unique_id_order_list = all_permutations[min([int(len(all_permutations) * candidate[0, frame_idx].item()), len(all_permutations) - 1])]
        bbox_id_left2right_list = [unique_id_order_list[x] for x in range(len(unique_id_visibility_list)) if unique_id_visibility_list[x] > 0]

        curr_img = cv2.imread('/media/allenyljiang/Seagate_Backup_Plus_Drive/usr/local/VIBE-master/data/neurocomputing/05_0019/' + frame_list[frame_idx])
        for human_id in bbox_id_left2right_list:
            curr_human_coords = [mapping_node_id_to_bbox[x][0] for x in mapping_node_id_to_bbox if mapping_node_id_to_bbox[x][2] == frame_list[frame_idx]][bbox_id_left2right_list.index(human_id)]
            cv2.putText(curr_img, str(human_id), (int(curr_human_coords[0][0]), int(curr_human_coords[0][1])), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 255, 0), 3)
        cv2.imwrite(
            '/media/allenyljiang/Seagate_Backup_Plus_Drive/usr/local/VIBE-master/data/neurocomputing/results/mot20_test2/05_0019_vis/' + frame_list[frame_idx],
            curr_img)

    return result

def SSP_EM(result, mapping_edge_id_to_cost, mapping_node_id_to_bbox, mapping_node_id_to_features):
    split_each_track, split_each_track_valid_mask = update_split_each_track_valid_mask(result)
    # pca analysis
    all_feature_vectors_tensor = np.array([mapping_node_id_to_features[x] for x in mapping_node_id_to_features])
    # determine the number of principal components
    num_components = obtain_num_components(split_each_track, mapping_node_id_to_features)
    pca = PCA(n_components=num_components)
    pca.fit(all_feature_vectors_tensor)
    projection_bases = pca.components_
    mapping_node_id_to_features_dimension_reduced = pca.transform(np.array([mapping_node_id_to_features[x] for x in mapping_node_id_to_features]))
    mapping_node_id_to_features_dimension_reduced = mapping_node_id_to_features_dimension_reduced/np.max(mapping_node_id_to_features_dimension_reduced)
    mapping_node_id_to_features_dimension_reduced_dict = {}
    for mapping_node_id_to_features_key in mapping_node_id_to_features:
        mapping_node_id_to_features_dimension_reduced_dict[mapping_node_id_to_features_key] = mapping_node_id_to_features_dimension_reduced[[x for x in mapping_node_id_to_features].index(mapping_node_id_to_features_key), :]

    if (True in [(0 in y) for y in [split_each_track_valid_mask[x] for x in split_each_track_valid_mask]]) and (len(split_each_track) > 1):
        init_clusters = {}
        # initialize cluster centers
        for track_key in split_each_track:
            init_clusters[track_key] = {}
            init_clusters[track_key]['elements'] = []
            init_clusters[track_key]['elements_ids'] = []
            init_clusters[track_key]['mean'] = []
            init_clusters[track_key]['variance'] = [np.zeros((num_components, num_components))]
            for valid_instant in [x for x in range(len(split_each_track[track_key])) if (x % 2 == 0 and int(split_each_track[track_key][x][0]) - int(split_each_track[track_key][x][1]) == -1)]:
                init_clusters[track_key]['elements'].append(mapping_node_id_to_features_dimension_reduced_dict[int(int(split_each_track[track_key][valid_instant][1]) / 2)])
                init_clusters[track_key]['elements_ids'].append([int(int(split_each_track[track_key][valid_instant][1]) / 2) * 2 - 1, int(int(split_each_track[track_key][valid_instant][1]) / 2) * 2])
            if len(init_clusters[track_key]['elements']) > 0:
                init_clusters[track_key]['mean'] = np.mean(np.array(init_clusters[track_key]['elements']), axis=0)
                for idx_element in range(len(init_clusters[track_key]['elements'])):
                    init_clusters[track_key]['variance'][0] += np_cov(np.array(init_clusters[track_key]['elements'][idx_element] - init_clusters[track_key]['mean']), num_components)
        # initialize unsigned nodes
        invalid_boundary_nodes = []
        for track_key in split_each_track:
            #invalid_instant_start = [x for x in range(len(split_each_track_valid_mask[track_key])) if split_each_track_valid_mask[track_key][x] == 0]
            if (0 in split_each_track_valid_mask[track_key]) or (-1 in split_each_track_valid_mask[track_key]):
                invalid_boundary_nodes += [x for x in split_each_track[track_key] if split_each_track_valid_mask[track_key][split_each_track[track_key].index(x)] <= 0]
        em_nodes = []
        for track_key in split_each_track:
            for instant in range(len(split_each_track[track_key])):
                if (split_each_track[track_key][instant] in invalid_boundary_nodes) or ([split_each_track[track_key][instant][1], split_each_track[track_key][instant][0]] in invalid_boundary_nodes):
                    em_nodes += [y for y in [split_each_track[track_key][x] for x in range(instant, len(split_each_track[track_key])) if (x % 2 == 0 and int(split_each_track[track_key][x][0]) - int(split_each_track[track_key][x][1]) == -1)] if y not in em_nodes]
        em_nodes = [[int(x[0]), int(x[1])] for x in em_nodes]
        # start EM
        # remove the trajectories with only one node and the node resides in em_nodes
        init_clusters_invalid_key_list = []
        for track_key in split_each_track:
            if (len(init_clusters[track_key]['elements']) == 1) and (init_clusters[track_key]['elements_ids'][0] in em_nodes or [init_clusters[track_key]['elements_ids'][0][1], init_clusters[track_key]['elements_ids'][0][0]] in em_nodes):
                init_clusters_invalid_key_list.append(track_key)
        for init_clusters_invalid_key_list_item in init_clusters_invalid_key_list:
            del init_clusters[init_clusters_invalid_key_list_item]

        mixing_coefficient_list = np.array([len(init_clusters[x]['elements']) for x in init_clusters]) / (np.sum([len(init_clusters[x]['elements']) for x in init_clusters]) + len(em_nodes))
        responsibilities = np.zeros((len(em_nodes), len(init_clusters)))
        # start EM
        num_iter = 40
        EM_iter_idx = num_iter
        tmp_overall_sum_backup = 0.0
        while (EM_iter_idx > 0):
            # E step: estimate responsibilities and remove the nodes that do not belong to each cluster
            # ensure the rank of variance by avoiding two nodes from removing more than one nodes from one track
            init_clusters_backup = copy.deepcopy(init_clusters)
            for node in em_nodes:
                init_clusters = copy.deepcopy(init_clusters_backup)
                # remove curr node from init_clusters then compute responsibilities
                for track_key in init_clusters:
                    if EM_iter_idx == num_iter:
                        if (node in init_clusters[track_key]['elements_ids']) or ([node[1], node[0]] in init_clusters[track_key]['elements_ids']):
                            curr_node = node if (node in init_clusters[track_key]['elements_ids']) else [node[1], node[0]]
                            idx_to_remove = init_clusters[track_key]['elements_ids'].index(curr_node)
                            del init_clusters[track_key]['elements_ids'][idx_to_remove]
                            del init_clusters[track_key]['elements'][idx_to_remove]
                        init_clusters[track_key]['mean'] = np.mean(np.array(init_clusters[track_key]['elements']), axis=0)
                        init_clusters[track_key]['variance'] = [np.zeros((num_components, num_components))]
                        for idx_element in range(len(init_clusters[track_key]['elements'])):
                            init_clusters[track_key]['variance'][0] += np_cov(np.array(init_clusters[track_key]['elements'][idx_element] - init_clusters[track_key]['mean']), num_components)
                    responsibilities[em_nodes.index(node), [x for x in init_clusters].index(track_key)] = mixing_coefficient_list[[x for x in init_clusters].index(track_key)] * Gaussian_probability(mapping_node_id_to_features_dimension_reduced_dict[int(int(node[1])/2)], init_clusters[track_key]['mean'], init_clusters[track_key]['variance'][0])
            for responsibilities_row_idx in range(responsibilities.shape[0]):
                responsibilities[responsibilities_row_idx, :] = responsibilities[responsibilities_row_idx, :] / np.sum(responsibilities[responsibilities_row_idx, :])
            # M step: estimate the parameters of clusters
            for track_key in init_clusters:
                Nk = len(init_clusters[track_key]) + np.sum(responsibilities[:, [x for x in init_clusters].index(track_key)])
                init_clusters[track_key]['mean'] = np.zeros((num_components))
                init_clusters[track_key]['variance'] = [np.zeros((num_components, num_components))]
                init_clusters[track_key]['mean'] = np.mean(np.array(init_clusters[track_key]['elements']), axis=0)
                for idx_element in range(len(init_clusters[track_key]['elements'])):
                    init_clusters[track_key]['variance'][0] += np_cov(np.array(init_clusters[track_key]['elements'][idx_element] - init_clusters[track_key]['mean']), num_components)
                for node in em_nodes:
                    init_clusters[track_key]['mean'] = np.array(init_clusters[track_key]['mean']) + (1.0 / Nk) * responsibilities[em_nodes.index(node), [x for x in init_clusters].index(track_key)] * mapping_node_id_to_features_dimension_reduced_dict[int(int(node[1])/2)]
                    init_clusters[track_key]['variance'][0] = np.array(init_clusters[track_key]['variance'][0]) + (1.0 / Nk) * responsibilities[em_nodes.index(node), [x for x in init_clusters].index(track_key)] * \
                                                              np_cov(np.array(mapping_node_id_to_features_dimension_reduced_dict[int(int(node[1]) / 2)]) - init_clusters[track_key]['mean'], num_components)
                mixing_coefficient_list[[x for x in init_clusters].index(track_key)] = Nk / (np.sum([len(init_clusters[x]['elements']) for x in init_clusters]) + len(em_nodes))
            # compute log likelihood
            tmp_overall_sum = 0.0
            for node in em_nodes:
                # remove curr node from init_clusters then compute responsibilities
                tmp_sum = 0.0
                for track_key in init_clusters:
                    tmp_sum += mixing_coefficient_list[[x for x in init_clusters].index(track_key)] * Gaussian_probability(mapping_node_id_to_features_dimension_reduced_dict[int(int(node[1]) / 2)], init_clusters[track_key]['mean'], init_clusters[track_key]['variance'][0])
                tmp_overall_sum += np.log(tmp_sum)

            if EM_iter_idx < num_iter:
                if abs(tmp_overall_sum - tmp_overall_sum_backup) < 0.001:
                    break
                if tmp_overall_sum > tmp_overall_sum_backup:
                    break

            tmp_overall_sum_backup = copy.deepcopy(tmp_overall_sum)
            EM_iter_idx -= 1

        # prepare clean list
        clean_clusters = {}
        for track_key in split_each_track:
            if len([x for x in split_each_track[track_key] if ([int(x[0]), int(x[1])] in em_nodes or [int(x[1]), int(x[0])] in em_nodes or split_each_track_valid_mask[track_key][split_each_track[track_key].index(x)] <= 0)]) == 0:
                clean_clusters[track_key] = split_each_track[track_key]
                clean_clusters[track_key] = [x for x in clean_clusters[track_key] if (int(x[0]) % 2 == 1 and int(x[1]) % 2 == 0)]
            else:
                clean_clusters[track_key] = split_each_track[track_key][:split_each_track[track_key].index([x for x in split_each_track[track_key] if ([int(x[0]), int(x[1])] in em_nodes or [int(x[1]), int(x[0])] in em_nodes or split_each_track_valid_mask[track_key][split_each_track[track_key].index(x)] <= 0)][0])]
                clean_clusters[track_key] = [x for x in clean_clusters[track_key] if (int(x[0]) % 2 == 1 and int(x[1]) % 2 == 0)]
        # insert em_nodes to clean list
        for em_node in em_nodes:
            track_key = [x for x in split_each_track][np.argmax(responsibilities[em_nodes.index(em_node), :])]
            clean_clusters[track_key].append([str(em_node[0]), str(em_node[1])])
        for track_key in clean_clusters:
            clean_clusters[track_key].sort(key=lambda x: int(x[0]))
            clean_clusters[track_key] = interpolate_to_obtain_traj(clean_clusters[track_key])
        result[0] = 'Predicted tracks' + '\n' + convert_dict_to_str(result, clean_clusters)

    return result

######################################################################################################################################################
