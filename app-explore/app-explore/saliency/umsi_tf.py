"""UMSI++ saliency model (UEyes), rebuilt in tf_keras (Keras 2 API) so the published weights load on TF 2.x / py3.11.

Architecture: UMSI, "Predicting Visual Importance Across Graphic Design Types" (Fosco et al., UIST 2020): Xception
encoder (output stride 8), ASPP, a global classification branch fused back in, a convolutional decoder. Weights:
UMSI++ from "UEyes: Understanding Visual Saliency across User Interface Types" (Jiang et al., CHI 2023), trained on
eye-tracking data of UI screenshots, file `umsi++.hdf5` in https://userinterfaces.aalto.fi/ueyeschi23/model_weights.zip.
The original code needs Python 3.6 / Keras 2.2.4 / TF 1.14; this file rebuilds the network by layer name and loads the
weights with load_weights(by_name=True).

Licences, as checked on 2026-11-10:
- UMSI code (github.com/diviz-mit/predimportance-public, LICENSE): copyright 2020 Fosco, Casser, Bedi, O'Donovan,
  Hertzmann, Bylinskii, MIT and Adobe; "for non-commercial research purposes only", BSD-style redistribution terms;
  commercial licensing via hertzman@adobe.com.
- UEyes code (github.com/YueJiang-nj/UEyes-CHI2023, whose saliency_models/UMSI++ holds the UMSI++ model definition):
  licence not stated (no LICENSE file, none in the READMEs).
- UEyes dataset: CC BY 4.0. The weights page states no terms.
This file copies no source text from either repository: it is written anew in tf_keras. It does reproduce the layer
graph of the UEyes UMSI++ model definition (layer types, sizes, order and names, which load_weights(by_name=True)
needs), so it is a derivative of that architecture; the Xception part follows keras.applications (MIT).
Weights are downloaded by the user (setup.sh, sha256-checked), never redistributed with the skill. Only UMSI++ is
used here; the original UMSI weights (non-commercial licence) are not downloaded, the "umsi" variant below exists
only because both share this builder.
"""
import os
os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")
import numpy as np
import tensorflow as tf
import tf_keras as keras
from tf_keras import layers as L
from PIL import Image


def _xception_os8(inp):
    # Xception with blocks 4 and 13 strides removed (output stride 8), names as in Keras 2.2.4 file.
    x = L.Conv2D(32, 3, strides=2, use_bias=False, name="block1_conv1")(inp)
    x = L.BatchNormalization(name="block1_conv1_bn")(x); x = L.Activation("relu", name="block1_conv1_act")(x)
    x = L.Conv2D(64, 3, use_bias=False, name="block1_conv2")(x)
    x = L.BatchNormalization(name="block1_conv2_bn")(x); x = L.Activation("relu", name="block1_conv2_act")(x)
    r = L.Conv2D(128, 1, strides=2, padding="same", use_bias=False, name="conv2d_1")(x)
    r = L.BatchNormalization(name="batch_normalization_1")(r)
    x = L.SeparableConv2D(128, 3, padding="same", use_bias=False, name="block2_sepconv1")(x)
    x = L.BatchNormalization(name="block2_sepconv1_bn")(x); x = L.Activation("relu", name="block2_sepconv2_act")(x)
    x = L.SeparableConv2D(128, 3, padding="same", use_bias=False, name="block2_sepconv2")(x)
    x = L.BatchNormalization(name="block2_sepconv2_bn")(x)
    x = L.MaxPooling2D(3, strides=2, padding="same", name="block2_pool")(x)
    x = L.add([x, r], name="add_1")
    r = L.Conv2D(256, 1, strides=2, padding="same", use_bias=False, name="conv2d_2")(x)
    r = L.BatchNormalization(name="batch_normalization_2")(r)
    x = L.Activation("relu", name="block3_sepconv1_act")(x)
    x = L.SeparableConv2D(256, 3, padding="same", use_bias=False, name="block3_sepconv1")(x)
    x = L.BatchNormalization(name="block3_sepconv1_bn")(x); x = L.Activation("relu", name="block3_sepconv2_act")(x)
    x = L.SeparableConv2D(256, 3, padding="same", use_bias=False, name="block3_sepconv2")(x)
    x = L.BatchNormalization(name="block3_sepconv2_bn")(x)
    x = L.MaxPooling2D(3, strides=2, padding="same", name="block3_pool")(x)
    x = L.add([x, r], name="add_2")
    r = L.Conv2D(728, 1, padding="same", use_bias=False, name="conv2d_3")(x)
    r = L.BatchNormalization(name="batch_normalization_3")(r)
    x = L.Activation("relu", name="block4_sepconv1_act")(x)
    x = L.SeparableConv2D(728, 3, padding="same", use_bias=False, name="block4_sepconv1")(x)
    x = L.BatchNormalization(name="block4_sepconv1_bn")(x); x = L.Activation("relu", name="block4_sepconv2_act")(x)
    x = L.SeparableConv2D(728, 3, padding="same", use_bias=False, name="block4_sepconv2")(x)
    x = L.BatchNormalization(name="block4_sepconv2_bn")(x)
    x = L.MaxPooling2D(3, strides=1, padding="same", name="block4_pool")(x)
    x = L.add([x, r], name="add_3")
    for i in range(8):
        r, p = x, f"block{i + 5}"
        for j in (1, 2, 3):
            x = L.Activation("relu", name=f"{p}_sepconv{j}_act")(x)
            x = L.SeparableConv2D(728, 3, padding="same", use_bias=False, name=f"{p}_sepconv{j}")(x)
            x = L.BatchNormalization(name=f"{p}_sepconv{j}_bn")(x)
        x = L.add([x, r], name=f"add_{i + 4}")
    r = L.Conv2D(1024, 1, padding="same", use_bias=False, name="conv2d_4")(x)
    r = L.BatchNormalization(name="batch_normalization_4")(r)
    x = L.Activation("relu", name="block13_sepconv1_act")(x)
    x = L.SeparableConv2D(728, 3, padding="same", use_bias=False, name="block13_sepconv1")(x)
    x = L.BatchNormalization(name="block13_sepconv1_bn")(x); x = L.Activation("relu", name="block13_sepconv2_act")(x)
    x = L.SeparableConv2D(1024, 3, padding="same", use_bias=False, name="block13_sepconv2")(x)
    x = L.BatchNormalization(name="block13_sepconv2_bn")(x)
    x = L.MaxPooling2D(3, strides=1, padding="same", name="block13_pool")(x)
    x = L.add([x, r], name="add_12")
    x = L.SeparableConv2D(1536, 3, padding="same", use_bias=False, name="block14_sepconv1")(x)
    x = L.BatchNormalization(name="block14_sepconv1_bn")(x); x = L.Activation("relu", name="block14_sepconv1_act")(x)
    x = L.SeparableConv2D(2048, 3, padding="same", use_bias=False, name="block14_sepconv2")(x)
    x = L.BatchNormalization(name="block14_sepconv2_bn")(x)
    return L.Activation("relu", name="block14_sepconv2_act")(x)


def build_umsi(input_hw, out_name, original):
    # original UMSI (2020 full-model h5): head BN eps 1e-5, decoder convs dilated(2)+bias+relu.
    # UMSI++ (UEyes code): Keras-default BN eps, plain linear bias-free decoder convs.
    eps = 1e-5 if original else 1e-3
    BN = lambda name: L.BatchNormalization(epsilon=eps, name=name)
    dk = dict(padding="same", use_bias=original, activation="relu" if original else None,
              dilation_rate=2 if original else 1)
    h, w = input_hw
    inp = L.Input((h, w, 3), name="input_1")
    f = _xception_os8(inp)
    fh, fw = f.shape[1], f.shape[2]
    c0 = L.Conv2D(256, 1, padding="same", use_bias=False, name="aspp_csep0")(f)
    br = []
    for d, a, b in ((6, 2, 3), (12, 4, 5), (18, 6, 7)):
        c = L.DepthwiseConv2D(3, dilation_rate=d, padding="same", use_bias=False, name=f"aspp_csepd{d}_depthwise")(f)
        c = BN(f"aspp_csepd{d}_depthwise_BN")(c)
        c = L.Activation("relu", name=f"activation_{a}")(c)
        c = L.Conv2D(256, 1, padding="same", use_bias=False, name=f"aspp_csepd{d}_pointwise")(c)
        c = BN(f"aspp_csepd{d}_pointwise_BN")(c)
        br.append(L.Activation("relu", name=f"activation_{b}")(c))
    c0 = L.Activation("relu", name="aspp0_activation")(BN("aspp0_BN")(c0))
    concat1 = L.Concatenate(name="concatenate_1")([c0] + br)
    x = L.Conv2D(256, 3, strides=3, padding="same", use_bias=False, name="global_conv")(f)
    x = L.Activation("relu", name="activation_1")(BN("global_BN")(x))
    x = L.GlobalAveragePooling2D(name="global_average_pooling2d_1")(x)
    x = L.Dense(256, name="global_dense")(x)
    out_classif = L.Dense(6, activation="softmax", name="out_classif")(x)
    x = L.Dense(256, name="dense_fusion")(x)
    x = L.Lambda(lambda t: tf.tile(t[:, None, None, :], [1, fh, fw, 1]), name="lambda_1")(x)
    x = L.Concatenate(name="concatenate_2")([concat1, x])
    x = L.Conv2D(256, 1, padding="same", use_bias=False, name="concat_projection")(x)
    x = L.Activation("relu", name="activation_8")(BN("concat_projection_BN")(x))
    x = L.Conv2D(256, 3, **dk, name="dec_c1")(x)
    x = L.Conv2D(256, 3, **dk, name="dec_c2")(x)
    x = L.UpSampling2D(2, interpolation="bilinear", name="dec_ups1")(x)
    x = L.Conv2D(128, 3, **dk, name="dec_c3")(x)
    x = L.Conv2D(128, 3, **dk, name="dec_c4")(x)
    x = L.UpSampling2D(2, interpolation="bilinear", name="dec_ups2")(x)
    x = L.Conv2D(64, 3, **dk, name="dec_c5")(x)
    x = L.UpSampling2D(4, interpolation="bilinear", name="dec_ups3")(x)
    out = L.Conv2D(1, 1, padding="same", use_bias=original, activation="relu" if original else None, name=out_name)(x)
    return keras.Model(inp, [out, out_classif])


VARIANTS = {  # name: (weights file, input HxW, output layer name, original-UMSI head)
    "umsi": ("umsi.h5", (240, 320), "dec_c_out", True),
    "umsi++": ("umsi++.hdf5", (256, 256), "dec_c_cout", False),
}


def load(variant, weights_path):
    _, hw, out_name, relu_bias = VARIANTS[variant]
    m = build_umsi(hw, out_name, relu_bias)
    m.load_weights(weights_path, by_name=True, skip_mismatch=False)
    return m


def predict(model, path):
    """Return float32 HxW saliency map at the screenshot's resolution, summing to 1."""
    img = Image.open(path).convert("RGB")
    W, H = img.size
    h, w = model.input_shape[1:3]
    s = min(h / H, w / W)                       # letterbox, as in the authors' padding()
    nh, nw = round(H * s), round(W * s)
    top, left = (h - nh) // 2, (w - nw) // 2
    x = np.zeros((h, w, 3), np.float32)
    x[top:top + nh, left:left + nw] = np.asarray(img.resize((nw, nh), Image.BILINEAR), np.float32)[..., ::-1]  # BGR
    x -= np.array([103.939, 116.779, 123.68], np.float32)
    pred = model(x[None], training=False)[0][0, ..., 0].numpy()   # output is 2x input size
    k = pred.shape[0] // h
    pred = pred[k * top:k * (top + nh), k * left:k * (left + nw)]
    sal = np.asarray(Image.fromarray(pred).resize((W, H), Image.BILINEAR), np.float32)
    sal = np.clip(sal, 0, None)
    return (sal / sal.sum()).astype(np.float32)
