import argparse
import logging
import math
import os
import os.path as osp
import random
import sys
import cv2
from collections import defaultdict
from glob import glob
from tqdm import tqdm

import numpy as np
import torch
import torch.distributed as dist
import torch.multiprocessing as mp
from tensorboardX import SummaryWriter

sys.path.append("../../")
import utils as util
import utils.option as option
from data import create_dataloader, create_dataset
from data.data_sampler import DistIterSampler
from metrics import IQA
from models import create_model

print(torch.cuda.current_device())

#### options
parser = argparse.ArgumentParser()
parser.add_argument(
    "-opt",
    type=str,
    default="options/test/2020Track2.yml",
    help="Path to options YMAL file.",
)
parser.add_argument("-input_dir", type=str, default="../../../data_samples/LR")
parser.add_argument("-output_dir", type=str, default="../../../data_samples/PDM-SR/")
args = parser.parse_args()
opt = option.parse(args.opt, is_train=False)

opt = option.dict_to_nonedict(opt)

model = create_model(opt)

if not osp.exists(args.output_dir):
    os.makedirs(args.output_dir)

test_files = glob(osp.join(args.input_dir, "*"))
for inx, path in tqdm(enumerate(test_files)):
    name = path.split("/")[-1].split(".")[0]
    print(name)

    img = cv2.imread(path)[:, :, [2, 1, 0]]
    img = img.transpose(2, 0, 1)[None] / 255
    img_t = torch.as_tensor(np.ascontiguousarray(img)).float()

    model.test({"src": img_t})
    outdict = model.get_current_visuals()

    sr = outdict["sr"]
    sr_im = util.tensor2img(sr)
    
    name = name.replace("\\", "/")

    save_path = osp.join(args.output_dir, "{}_x{}.png".format(name, opt["scale"]))
    # save_path = args.output_dir+"/{}_x{}.png".format(name, opt["scale"])
    
    print(save_path)
    cv2.imwrite(save_path, sr_im)
