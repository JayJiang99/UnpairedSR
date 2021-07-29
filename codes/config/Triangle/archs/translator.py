import math

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable

from utils.registry import ARCH_REGISTRY


def default_conv(in_channels, out_channels, kernel_size, bias=True):
    return nn.Conv2d(
        in_channels, out_channels, kernel_size, padding=(kernel_size // 2), bias=bias
    )


class BasicBlock(nn.Sequential):
    def __init__(
        self,
        in_channels,
        out_channels,
        kernel_size,
        stride=1,
        bias=False,
        bn=True,
        act=nn.ReLU(True),
    ):

        m = [
            nn.Conv2d(
                in_channels,
                out_channels,
                kernel_size,
                padding=(kernel_size // 2),
                stride=stride,
                bias=bias,
            )
        ]
        if bn:
            m.append(nn.BatchNorm2d(out_channels))
        if act is not None:
            m.append(act)
        super(BasicBlock, self).__init__(*m)


class ResBlock(nn.Module):
    def __init__(
        self,
        conv,
        n_feat,
        kernel_size,
        bias=True,
        bn=False,
        act=nn.ReLU(True),
        res_scale=1,
    ):

        super(ResBlock, self).__init__()
        m = []
        for i in range(2):
            m.append(conv(n_feat, n_feat, kernel_size, bias=bias))
            if bn:
                m.append(nn.BatchNorm2d(n_feat))
            if i == 0:
                m.append(act)

        self.body = nn.Sequential(*m)
        self.res_scale = res_scale

    def forward(self, x):
        res = self.body(x).mul(self.res_scale)
        res += x

        return res


class Upsampler(nn.Sequential):
    def __init__(self, conv, scale, n_feat, bn=False, act=False, bias=True):

        m = []
        if (scale & (scale - 1)) == 0:  # Is scale = 2^n?
            for _ in range(int(math.log(scale, 2))):
                m.append(conv(n_feat, 4 * n_feat, 3, bias))
                m.append(nn.PixelShuffle(2))
                if bn:
                    m.append(nn.BatchNorm2d(n_feat))
                if act:
                    m.append(act())
        elif scale == 3:
            m.append(conv(n_feat, 9 * n_feat, 3, bias))
            m.append(nn.PixelShuffle(3))
            if bn:
                m.append(nn.BatchNorm2d(n_feat))
            if act:
                m.append(act())
        elif scale == 1:
            m.append(nn.Identity())
        else:
            raise NotImplementedError

        super(Upsampler, self).__init__(*m)

class Quant(torch.autograd.Function):

    @staticmethod
    def forward(ctx, input):
        output = torch.clamp(input, 0, 1)
        output = (output * 255.).round() / 255.
        return output

    @staticmethod
    def backward(ctx, grad_output):
        return grad_output

class Quantization(nn.Module):
    def __init__(self):
        super(Quantization, self).__init__()

    def forward(self, input):
        return Quant.apply(input)

@ARCH_REGISTRY.register()
class Translator(nn.Module):
    def __init__(self, nb, nf, scale=4, zero_tail=False, quant=False, conv=default_conv):
        super().__init__()

        self.scale = scale
        self.quant = quant
        if quant:
            self.quant = Quantization()

        # define head module
        if scale >= 1:
            m_head = [conv(3, nf, 3)]
        else:
            s = int(1 / scale)
            m_head = [nn.Conv2d(3, nf, kernel_size=2 * s + 1, stride=s, padding=s)]

        # define body module
        m_body = [
            ResBlock(conv, nf, 3, act=nn.ReLU(True), res_scale=1) for _ in range(nb)
        ]
        m_body.append(conv(nf, nf, 3))

        # define tail module
        m_tail = [
            Upsampler(conv, scale, nf, act=False) if scale > 1 else nn.Identity(),
            conv(nf, 3, 3),
        ]

        self.head = nn.Sequential(*m_head)
        self.body = nn.Sequential(*m_body)
        self.tail = nn.Sequential(*m_tail)

        if zero_tail:
            nn.init.constant_(self.tail[-1].weight, 0)
            nn.init.constant_(self.tail[-1].bias, 0)

    def forward(self, x):

        f = self.head(x)
        f = self.body(f)
        f = self.tail(f)

        if self.scale == 1:
            x = f + x
        else:
            x = f + F.interpolate(x, scale_factor=self.scale)
        
        if self.quant:
            x = self.quant(x)
        return x