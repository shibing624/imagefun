# -*- coding: utf-8 -*-
"""
@author:XuMing(xuming624@qq.com)
@description:

样式迁移常用的损失函数由3部分组成：内容损失使合成图像与内容图像在内容特征上接近，样式损失令合成图像与样式图像在样式特征上接近，
而总变差损失则有助于减少合成图像中的噪点。
可以通过预训练的卷积神经网络来抽取图像的特征，并通过最小化损失函数来不断更新合成图像。
用格拉姆矩阵表达样式层输出的样式。
"""
import argparse
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision
from PIL import Image

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# imagenet的数据均值、方差
rgb_mean = np.array([0.485, 0.456, 0.406])
rgb_std = np.array([0.229, 0.224, 0.225])


def to_tensor(PIL_img, image_shape):
    transform = torchvision.transforms.Compose([
        torchvision.transforms.Resize(image_shape),
        torchvision.transforms.ToTensor(),
        torchvision.transforms.Normalize(mean=rgb_mean, std=rgb_std)])

    return transform(PIL_img).unsqueeze(dim=0)  # (batch_size, 3, H, W)


def to_img(img_tensor):
    transform = torchvision.transforms.Normalize(
        mean=-rgb_mean / rgb_std,
        std=1 / rgb_std)
    to_PIL_image = torchvision.transforms.ToPILImage()
    return to_PIL_image(transform(img_tensor[0].cpu()).clamp(0, 1))


class TransferNet(nn.Module):
    def __init__(self):
        """Select conv1_1 ~ conv5_1 activation maps."""
        super().__init__()
        self.style_layers = [0, 5, 10, 19, 28]
        self.content_layers = [25]
        self.pretrained_net = torchvision.models.vgg19(pretrained=True)
        self.net = self.get_net()

    def get_net(self):
        # 在抽取特征时，我们只需要用到VGG从输入层到最靠近输出层的内容层或样式层之间的所有层。
        net_list = []
        for i in range(max(self.content_layers + self.style_layers) + 1):
            net_list.append(self.pretrained_net.features[i])
        net = torch.nn.Sequential(*net_list)
        return net.to(device)

    def forward(self, X):
        """Extract multiple convolutional feature maps."""
        # 需要中间层的输出，因此这里我们逐层计算，并保留内容层和样式层的输出。
        contents = []
        styles = []
        for i in range(len(self.net)):
            X = self.net[i](X)
            if i in self.style_layers:
                styles.append(X)
            if i in self.content_layers:
                contents.append(X)
        return contents, styles


def content_loss(Y_hat, Y):
    """内容损失"""
    return F.mse_loss(Y_hat, Y)


def gram(X):
    """用这样的格拉姆矩阵表达样式层输出的样式"""
    num_channels, n = X.shape[1], X.shape[2] * X.shape[3]
    X = X.view(num_channels, n)
    return torch.matmul(X, X.t()) / (num_channels * n)


def style_loss(Y_hat, gram_Y):
    """样式损失"""
    return F.mse_loss(gram(Y_hat), gram_Y)


def tv_loss(Y_hat):
    """
    合成图像里面有大量高频噪点，即有特别亮或者特别暗的颗粒像素。
    一种常用的降噪方法是总变差降噪（total variation de-noising）。
    降低总变差损失能够尽可能使邻近的像素值相似。
    :param Y_hat:
    :return:
    """
    return 0.5 * (F.l1_loss(Y_hat[:, :, 1:, :], Y_hat[:, :, :-1, :]) +
                  F.l1_loss(Y_hat[:, :, :, 1:], Y_hat[:, :, :, :-1]))


def compute_loss(X, contents_Y_hat, styles_Y_hat, contents_Y, styles_Y_gram,
                 content_weight, style_weight, tv_weight):
    # 样式迁移的损失函数即内容损失、样式损失和总变差损失的加权和。
    # 分别计算内容损失、样式损失和总变差损失
    contents_l = [content_loss(Y_hat, Y) * content_weight for Y_hat, Y in zip(
        contents_Y_hat, contents_Y)]
    styles_l = [style_loss(Y_hat, Y) * style_weight for Y_hat, Y in zip(
        styles_Y_hat, styles_Y_gram)]
    tv_l = tv_loss(X) * tv_weight
    # 对所有损失求和
    loss = sum(styles_l) + sum(contents_l) + tv_l
    return contents_l, styles_l, tv_l, loss


# 在样式迁移中，合成图像是唯一需要更新的变量。
class GeneratedImage(torch.nn.Module):
    def __init__(self, img_shape):
        super(GeneratedImage, self).__init__()
        self.weight = torch.nn.Parameter(torch.rand(*img_shape))

    def forward(self):
        return self.weight


# 样式图像在各个样式层的格拉姆矩阵styles_Y_gram将在训练前预先计算好。
def get_inits(X, lr, styles_Y):
    gen_img = GeneratedImage(X.shape).to(device)
    gen_img.weight.data = X.data
    optimizer = torch.optim.Adam(gen_img.parameters(), lr=lr)
    styles_Y_gram = [gram(Y) for Y in styles_Y]
    return gen_img(), styles_Y_gram, optimizer


# 训练
def train(net, X, contents_Y, styles_Y, lr, max_epochs, lr_decay_epoch,
          content_weight, style_weight, tv_weight, log_epochs):
    X, styles_Y_gram, optimizer = get_inits(X, lr, styles_Y)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, lr_decay_epoch, gamma=0.1)
    for i in range(max_epochs):
        start = time.time()

        contents_Y_hat, styles_Y_hat = net(X)
        contents_l, styles_l, tv_l, loss = compute_loss(X, contents_Y_hat, styles_Y_hat,
                                                        contents_Y, styles_Y_gram,
                                                        content_weight, style_weight, tv_weight)

        optimizer.zero_grad()
        loss.backward(retain_graph=True)
        optimizer.step()
        scheduler.step()

        if (i + 1) % log_epochs == 0:
            print('epoch %3d/%3d, content loss %.2f, style loss %.2f, '
                  'TV loss %.2f, total loss %.2f, %.2f sec/epoch'
                  % (i + 1, max_epochs, sum(contents_l).item(), sum(styles_l).item(), tv_l.item(), loss.item(),
                     time.time() - start))
    return X.detach()


def main(args):
    print("device:", device)
    content_img = Image.open(args.content_img_file)
    style_img = Image.open(args.style_img_file)
    image_shape = content_img.size
    if args.image_max_size < max(content_img.size):
        scale = args.image_max_size / max(content_img.size)
        image_shape = tuple((np.array(content_img.size) * scale).astype(int))

    print("image_shape:", image_shape)
    net = TransferNet().to(device).eval()
    # 对内容图像抽取内容特征
    content_X = to_tensor(content_img, image_shape).to(device)
    contents_Y, _ = net(content_X)
    # 对样式图像抽取样式特征
    style_X = to_tensor(style_img, image_shape).to(device)
    _, styles_Y = net(style_X)

    out_array = train(net, content_X, contents_Y, styles_Y, args.lr, args.max_epochs,
                      args.lr_decay_epoch, args.content_weight, args.style_weight, args.tv_weight, args.log_epochs)
    out_img = to_img(out_array)
    out_img.show()
    out_img.save(args.output_img_file)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--content_img_file', type=str, default='../samples/style_transfer_png/mount.png')
    parser.add_argument('--style_img_file', type=str, default='../samples/style_transfer_png/autumn.png')
    parser.add_argument('--image_max_size', type=int, default=600)
    parser.add_argument('--max_epochs', type=int, default=500)
    parser.add_argument('--log_epochs', type=int, default=20)
    parser.add_argument('--lr_decay_epoch', type=int, default=200)
    parser.add_argument('--content_weight', type=float, default=1, help="weight of content loss")
    parser.add_argument('--style_weight', type=float, default=1000, help="weight of style loss")
    parser.add_argument('--tv_weight', type=float, default=10, help="weight of total variation de-noising loss")
    parser.add_argument('--lr', type=float, default=0.003)
    parser.add_argument('--output_img_file', type=str, default='style_demo.png')
    args = parser.parse_args()
    print(args)
    main(args)
