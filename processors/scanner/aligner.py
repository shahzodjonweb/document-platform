"""DocAligner's two ONNX models, run directly.

DocAligner (Apache-2.0, github.com/DocsaidLab/DocAligner) ships a heatmap
model that finds the page corners (fastvit_sa24) and a point model whose
has_obj output scores whether a document is present. Its pip package and its
capybara dependency download the weights from Google Drive on first use, pull
in a GPU runtime on Linux and fetch a font on import; this module runs the
same weight files, pinned by hash in models.json, with the preprocessing
copied from the package: a bilinear resize to 256x256, CHW, float32 / 255.
"""
import cv2
import numpy as np

from .shadows import session

HEATMAP = 'fastvit_sa24_h_e_bifpn_256_fp32'
POINT = 'lcnet050_p_multi_decoder_l3_d64_256_fp32'


class Model:
    """One DocAligner network; ``model(img=...)`` returns its outputs by name."""

    img_size_infer = (256, 256)

    def __init__(self, name):
        self.session = session(name)
        self.outputs = [output.name for output in self.session.get_outputs()]

    def model(self, **inputs):
        return dict(zip(self.outputs, self.session.run(self.outputs, inputs)))


def preprocess(image, size):
    """The network input for a BGR uint8 image, as DocAligner prepares it."""
    height, width = size
    tensor = np.transpose(cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR),
                          (2, 0, 1)).astype('float32')
    return {'input': {'img': tensor[None] / 255.}}
