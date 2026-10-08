"""A complete sheet filling the photograph is proposed from its straight edges.

A phone photo of a sheet held in a car: the bright mask bleeds into the
dashboard and touches the frame, the closed edges trace the printed border,
and a hand covers part of one edge. No closed contour forms, yet the four
paper edges are long straight boundaries that must still produce the crop.
"""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from processors import document_scan
from processors.document_scan import prepare_image
from processors.line_outlines import line_candidates

FONT = Path(__file__).resolve().parents[1] / 'processors/assets/fonts/NotoSans-Regular.ttf'
CORNERS = np.array([(16, 15), (901, 20), (925, 1154), (72, 1205)], np.float32)


def held_sheet_in_car(*, sheet=True, hand=(-60, 470, 95, 650), dashboard=(205, 206, 208), seed=0):
    rng = np.random.default_rng(seed)
    width, height = 960, 1280
    seat = np.clip(rng.normal(44, 6, (height, width, 3)), 0, 255).astype(np.uint8)
    canvas = Image.fromarray(seat)
    ImageDraw.Draw(canvas).rectangle((0, 0, 260, 90), fill=dashboard)
    frame = np.asarray(canvas).copy()
    mask = np.zeros((height, width), bool)
    if sheet:
        font = ImageFont.truetype(str(FONT), 22)
        paper = np.full((1200, 900, 3), (236, 236, 232), np.uint8)
        shade = np.linspace(0, 28, 900)[None, :, None]
        paper = Image.fromarray(np.clip(paper.astype(np.int16) - shade, 0, 255).astype(np.uint8))
        draw = ImageDraw.Draw(paper)
        draw.rectangle((48, 70, 852, 1130), outline=(40, 40, 40), width=3)
        for row, y in enumerate(range(90, 1110, 34)):
            draw.text((64, y), f'Line {row}: consignee, shipper and route details for the shipment record',
                      font=font, fill=(32, 32, 32))
        for y in range(300, 1100, 160):
            draw.line((48, y, 852, y), fill=(50, 50, 50), width=2)
        source = np.array([(0, 0), (899, 0), (899, 1199), (0, 1199)], np.float32)
        pose = cv2.getPerspectiveTransform(source, CORNERS)
        warped = cv2.warpPerspective(np.asarray(paper), pose, (width, height))
        mask = cv2.warpPerspective(np.full((1200, 900), 255, np.uint8), pose, (width, height)) > 0
        frame[mask] = warped[mask]
    image = Image.fromarray(frame)
    if hand is not None:
        ImageDraw.Draw(image).ellipse(hand, fill=(176, 128, 104))
    return image, mask


def _thumbnail_parts(image):
    small = document_scan._thumbnail(image)
    rgb = np.asarray(small)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 35, 110)
    return gray, cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[:, :, 1], edges, cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)


def test_held_sheet_filling_the_frame_is_cropped_from_its_straight_edges():
    image, mask = held_sheet_in_car()
    found = line_candidates(*_thumbnail_parts(image))
    assert len(found) == 1, 'The four paper edges assemble exactly one qualified sheet'
    quad = document_scan._order(found[0]['quad'])
    assert np.abs(quad - CORNERS).max() < 12, quad
    result, metadata = prepare_image(image, enhance_text=False)
    assert metadata == {'document_detected': True, 'cropped': True, 'enhanced': False}
    assert abs(result.width / result.height - 900 / 1200) < .03, 'The crop has the sheet\'s aspect'
    assert .82 < result.width * result.height / (900 * 1200) < 1.02, 'The crop is the whole sheet'
    before = int(((np.asarray(image.convert('L')) < 90) & mask).sum())
    after = int((np.asarray(result.convert('L')) < 90).sum())
    assert after > before * .9, 'Printed text survives the crop'
    cleaned, flags = prepare_image(image)
    assert flags['cropped'] and flags['enhanced'] and cleaned.size == result.size


def test_straight_edges_do_not_invent_a_sheet():
    empty, _ = held_sheet_in_car(sheet=False, hand=(-60, 380, 95, 760))
    assert line_candidates(*_thumbnail_parts(empty)) == []
    result, metadata = prepare_image(empty, enhance_text=False)
    assert metadata == {'document_detected': False, 'cropped': False, 'enhanced': False}
    assert result.tobytes() == empty.tobytes()


def test_a_hand_over_most_of_an_edge_keeps_the_photo_uncropped():
    # The edge is observed above and below a small hand; a hand covering a
    # third of the edge leaves its position uncertain and nothing is guessed.
    covered, _ = held_sheet_in_car(hand=(-60, 380, 95, 760))
    assert line_candidates(*_thumbnail_parts(covered)) == []
    result, metadata = prepare_image(covered, enhance_text=False)
    assert metadata['cropped'] is False and result.tobytes() == covered.tobytes()


def test_flat_scan_offers_no_straight_edge_proposal():
    from tests.test_image_scanning import full_frame_scan
    flat = full_frame_scan()
    assert line_candidates(*_thumbnail_parts(flat)) == []
    _, metadata = prepare_image(flat, enhance_text=False)
    assert metadata['cropped'] is False
