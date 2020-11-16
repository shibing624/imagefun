# -*- coding: utf-8 -*-
"""
@author:XuMing(xuming624@qq.com)
@description: 
"""

import os

import torch
import torch.nn as nn
from torchvision.utils import save_image

from cvnet.dataset import mnist

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

latent_size = 64
hidden_size = 128
image_size = 784
num_epochs = 20
batch_size = 128
sample_dir = "samples"

data_loader = mnist.load_data_mnist_without_cfg(batch_size=batch_size)

# Discriminator
D = nn.Sequential(
    nn.Linear(image_size, hidden_size),
    nn.LeakyReLU(0.2),
    nn.Linear(hidden_size, hidden_size),
    nn.LeakyReLU(0.2),
    nn.Linear(hidden_size, 1),
    nn.Sigmoid()
)

# Generator
G = nn.Sequential(
    nn.Linear(latent_size, hidden_size),
    nn.ReLU(),
    nn.Linear(hidden_size, hidden_size),
    nn.ReLU(),
    nn.Linear(hidden_size, image_size),
    nn.Tanh()
)

D = D.to(device)
G = G.to(device)

# Binary cross entropy loss and optimizer
loss_fn = nn.BCELoss()
d_optimizer = torch.optim.Adam(D.parameters(), lr=0.0002)
g_optimizer = torch.optim.Adam(G.parameters(), lr=0.0002)


def denorm(x):
    out = (x + 1) / 2
    return out.clamp(0, 1)


def reset_grad():
    d_optimizer.zero_grad()
    g_optimizer.zero_grad()


# train
total_step = len(data_loader)
for epoch in range(num_epochs):
    for i, (images, _) in enumerate(data_loader):
        images = images.reshape(batch_size, -1).to(device)

        # labels
        real_labels = torch.ones(batch_size, 1).to(device)
        fake_labels = torch.zeros(batch_size, 1).to(device)

        # train discriminator
        outputs = D(images)
        d_loss_real = loss_fn(outputs, real_labels)
        real_score = outputs

        # compute loss with fake image
        z = torch.randn(batch_size, latent_size).to(device)
        fake_images = G(z)
        outputs = D(fake_images)
        d_loss_fake = loss_fn(outputs, fake_labels)
        fake_score = outputs

        d_loss = d_loss_real + d_loss_fake
        reset_grad()
        d_loss.backward()
        d_optimizer.step()

        # train generator
        g_loss = loss_fn(outputs, real_labels)
        # backprop and optimizer
        reset_grad()
        g_loss.backward()
        g_optimizer.step()

        if (i + 1) % 200 == 0:
            print('Epoch [{}/{}], Step [{}/{}], d_loss: {:.4f}, g_loss: {:.4f}, D(x): {:.4f}, D(G(z)): {:.4f}'.format(
                epoch, num_epochs, i + 1, total_step, d_loss.item(), g_loss.item(), real_score.mean().item(),
                fake_score.mean().item()
            ))
    # Save real image
    images = images.reshape(images.size(0), 1, 28, 28)
    save_image(denorm((images), os.path.join(sample_dir, 'real_images_{}.png'.format(epoch + 1))))

    # Save sampled images
    fake_images = fake_images.reshape(fake_images.size(0), 1, 28, 28)
    save_image(denorm(fake_images), os.path.join(sample_dir, 'fake_images_{}.png'.format(epoch + 1)))

# Save the model checkpoints
torch.save(G.state_dict(), 'G.ckpt')
torch.save(D.state_dict(), 'D.ckpt')
