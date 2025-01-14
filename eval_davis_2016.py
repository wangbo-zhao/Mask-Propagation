import os
from os import path
import time
from argparse import ArgumentParser

import torch
from torch.utils.data import Dataset, DataLoader
import numpy as np
from PIL import Image

from model.eval_network import PropagationNetwork
from dataset.davis_test_dataset import DAVISTestDataset
from inference_core import InferenceCore

from progressbar import progressbar


"""
Arguments loading
"""
parser = ArgumentParser()
parser.add_argument('--model', default='saves/propagation_model.pth')
parser.add_argument('--davis', default='../DAVIS/2016')
parser.add_argument('--output')
parser.add_argument('--no_top', action='store_true')
args = parser.parse_args()

davis_path = args.davis
out_path = args.output

# Simple setup
os.makedirs(out_path, exist_ok=True)

torch.autograd.set_grad_enabled(False)

# Setup Dataset, a small hack to use the image set in the 2017 folder because the 2016 one is of a different format
test_dataset = DAVISTestDataset(davis_path, imset='../../2017/trainval/ImageSets/2016/val.txt', single_object=True)
test_loader = DataLoader(test_dataset, batch_size=1, shuffle=False, num_workers=4, pin_memory=True)

# Load our checkpoint
prop_saved = torch.load(args.model)
top_k = None if args.no_top else 50
prop_model = PropagationNetwork(top_k=top_k).cuda().eval()
prop_model.load_state_dict(prop_saved)

total_process_time = 0
total_frames = 0

# Start eval
for data in progressbar(test_loader, max_value=len(test_loader), redirect_stdout=True):

    rgb = data['rgb'].cuda()
    msk = data['gt'][0].cuda()
    info = data['info']
    name = info['name'][0]
    k = len(info['labels'][0])

    torch.cuda.synchronize()
    process_begin = time.time()

    processor = InferenceCore(prop_model, rgb, k)
    processor.interact(msk[:,0], 0, rgb.shape[1])

    # Do unpad -> upsample to original size 
    out_masks = torch.zeros((processor.t, 1, *rgb.shape[-2:]), dtype=torch.float32, device='cuda')
    for ti in range(processor.t):
        prob = processor.prob[:,ti]

        if processor.pad[2]+processor.pad[3] > 0:
            prob = prob[:,:,processor.pad[2]:-processor.pad[3],:]
        if processor.pad[0]+processor.pad[1] > 0:
            prob = prob[:,:,:,processor.pad[0]:-processor.pad[1]]

        out_masks[ti] = prob[1]*255
    
    out_masks = (out_masks.detach().cpu().numpy()[:,0]).astype(np.uint8)

    torch.cuda.synchronize()
    total_process_time += time.time() - process_begin
    total_frames += out_masks.shape[0]

    this_out_path = path.join(out_path, name)
    os.makedirs(this_out_path, exist_ok=True)
    for f in range(out_masks.shape[0]):
        img_E = Image.fromarray(out_masks[f])
        img_E.save(os.path.join(this_out_path, '{:05d}.png'.format(f)))

    del rgb
    del msk
    del processor

print('Total processing time: ', total_process_time)
print('Total processed frames: ', total_frames)
print('FPS: ', total_frames / total_process_time)