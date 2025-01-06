import copy
from typing import Any, Dict, List, Optional
from copy import deepcopy
from typing import List, Tuple, Any, Optional

from pydantic import BaseModel, computed_field, field_validator

from surya.postprocessing.util import rescale_bbox


class PolygonBox(BaseModel):
    polygon: List[List[float]]
    confidence: Optional[float] = None

    @field_validator('polygon')
    @classmethod
    def check_elements(cls, v: List[List[float]]) -> List[List[float]]:
        if len(v) != 4:
            raise ValueError('corner must have 4 elements')

        for corner in v:
            if len(corner) != 2:
                raise ValueError('corner must have 2 elements')
        return v

    @property
    def height(self):
        return self.bbox[3] - self.bbox[1]

    @property
    def width(self):
        return self.bbox[2] - self.bbox[0]

    @property
    def area(self):
        return self.width * self.height

    @computed_field
    @property
    def bbox(self) -> List[float]:
        box = [self.polygon[0][0], self.polygon[0][1], self.polygon[1][0], self.polygon[2][1]]
        if box[0] > box[2]:
            box[0], box[2] = box[2], box[0]
        if box[1] > box[3]:
            box[1], box[3] = box[3], box[1]
        return box

    def rescale(self, processor_size, image_size):
        # Point is in x, y format
        page_width, page_height = processor_size

        img_width, img_height = image_size
        width_scaler = img_width / page_width
        height_scaler = img_height / page_height

        new_corners = copy.deepcopy(self.polygon)
        for corner in new_corners:
            corner[0] = int(corner[0] * width_scaler)
            corner[1] = int(corner[1] * height_scaler)
        self.polygon = new_corners

    def fit_to_bounds(self, bounds):
        new_corners = copy.deepcopy(self.polygon)
        for corner in new_corners:
            corner[0] = max(min(corner[0], bounds[2]), bounds[0])
            corner[1] = max(min(corner[1], bounds[3]), bounds[1])
        self.polygon = new_corners

    def merge(self, other):
        x1 = min(self.bbox[0], other.bbox[0])
        y1 = min(self.bbox[1], other.bbox[1])
        x2 = max(self.bbox[2], other.bbox[2])
        y2 = max(self.bbox[3], other.bbox[3])
        self.polygon = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    def intersection_polygon(self, other) -> List[List[float]]:
        new_poly = []
        for i in range(4):
            if i == 0:
                new_corner = [max(self.polygon[0][0], other.polygon[0][0]), max(self.polygon[0][1], other.polygon[0][1])]
            elif i == 1:
                new_corner = [min(self.polygon[1][0], other.polygon[1][0]), max(self.polygon[1][1], other.polygon[1][1])]
            elif i == 2:
                new_corner = [min(self.polygon[2][0], other.polygon[2][0]), min(self.polygon[2][1], other.polygon[2][1])]
            elif i == 3:
                new_corner = [max(self.polygon[3][0], other.polygon[3][0]), min(self.polygon[3][1], other.polygon[3][1])]
            new_poly.append(new_corner)

        return new_poly

    def intersection_area(self, other, x_margin=0, y_margin=0):
        x_overlap = self.x_overlap(other, x_margin)
        y_overlap = self.y_overlap(other, y_margin)
        return x_overlap * y_overlap

    def x_overlap(self, other, x_margin=0):
        return max(0, min(self.bbox[2] + x_margin, other.bbox[2] + x_margin) - max(self.bbox[0] - x_margin, other.bbox[0] - x_margin))

    def y_overlap(self, other, y_margin=0):
        return max(0, min(self.bbox[3] + y_margin, other.bbox[3] + y_margin) - max(self.bbox[1] - y_margin, other.bbox[1] - y_margin))

    def intersection_pct(self, other, x_margin=0, y_margin=0):
        assert 0 <= x_margin <= 1
        assert 0 <= y_margin <= 1
        if self.area == 0:
            return 0

        if x_margin:
            x_margin = int(min(self.width, other.width) * x_margin)
        if y_margin:
            y_margin = int(min(self.height, other.height) * y_margin)

        intersection = self.intersection_area(other, x_margin, y_margin)
        return intersection / self.area

    def shift(self, x_shift: float | None = None, y_shift: float | None = None):
        if x_shift is not None:
            for corner in self.polygon:
                corner[0] += x_shift
        if y_shift is not None:
            for corner in self.polygon:
                corner[1] += y_shift


class Bbox(BaseModel):
    bbox: List[float]

    @field_validator('bbox')
    @classmethod
    def check_4_elements(cls, v: List[float]) -> List[float]:
        if len(v) != 4:
            raise ValueError('bbox must have 4 elements')
        return v

    def rescale_bbox(self, orig_size, new_size):
        self.bbox = rescale_bbox(self.bbox, orig_size, new_size)

    def round_bbox(self, divisor):
        self.bbox = [x // divisor * divisor for x in self.bbox]

    @property
    def height(self):
        return self.bbox[3] - self.bbox[1]

    @property
    def width(self):
        return self.bbox[2] - self.bbox[0]

    @property
    def area(self):
        return self.width * self.height

    @property
    def polygon(self):
        return [[self.bbox[0], self.bbox[1]], [self.bbox[2], self.bbox[1]], [self.bbox[2], self.bbox[3]], [self.bbox[0], self.bbox[3]]]

    @property
    def center(self):
        return [(self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2]

    def intersection_pct(self, other):
        if self.area == 0:
            return 0

        x_overlap = max(0, min(self.bbox[2], other.bbox[2]) - max(self.bbox[0], other.bbox[0]))
        y_overlap = max(0, min(self.bbox[3], other.bbox[3]) - max(self.bbox[1], other.bbox[1]))
        intersection = x_overlap * y_overlap
        return intersection / self.area


class LayoutBox(PolygonBox):
    label: str
    position: int
    top_k: Optional[Dict[str, float]] = None


class ColumnLine(Bbox):
    vertical: bool
    horizontal: bool


class TextLine(PolygonBox):
    text: str
    confidence: Optional[float] = None


class OCRResult(BaseModel):
    text_lines: List[TextLine]
    languages: List[str] | None = None
    image_bbox: List[float]


class TextDetectionResult(BaseModel):
    bboxes: List[PolygonBox]
    vertical_lines: List[ColumnLine]
    heatmap: Optional[Any]
    affinity_map: Optional[Any]
    image_bbox: List[float]


class LayoutResult(BaseModel):
    bboxes: List[LayoutBox]
    image_bbox: List[float]
    sliced: bool = False  # Whether the image was sliced and reconstructed


class TableCell(PolygonBox):
    row_id: int
    colspan: int
    within_row_id: int
    cell_id: int
    rowspan: int | None = None
    merge_up: bool = False
    merge_down: bool = False
    col_id: int | None = None

    @property
    def label(self):
        return f'{self.row_id} {self.rowspan}/{self.colspan}'


class TableRow(PolygonBox):
    row_id: int

    @property
    def label(self):
        return f'Row {self.row_id}'


class TableCol(PolygonBox):
    col_id: int

    @property
    def label(self):
        return f'Column {self.col_id}'


class TableResult(BaseModel):
    cells: List[TableCell]
    unmerged_cells: List[TableCell]
    rows: List[TableRow]
    cols: List[TableCol]
    image_bbox: List[float]


class OCRErrorDetectionResult(BaseModel):
    texts: List[str]
    labels: List[str]