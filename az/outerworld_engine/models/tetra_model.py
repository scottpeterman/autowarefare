"""
Wireframe model converted from tetra.an8

Source mesh : 5 points, 5 faces
Edges       : 8 unique (deduped from 16 face perimeter walks)
Bounds      : X[-9.99, 9.99]  Y[0.00, 19.97]  Z[-9.99, 9.99]
Y shift     : +9.9853 (ground-aligned: lowest vertex placed at y=0)

Coordinate convention: +Y = up (matches Anim8or source and the
Castle of Bane / Battlezone entity-local-space convention).
No axis flip is applied. The original Heminger PHP exporter
negated all three axes; we do not.
"""

TETRA_MODEL = {
    "lines": [
        ((-9.9853, 0, -9.9853), (9.9853, 0, -9.9853)),
        ((9.9853, 0, -9.9853), (-0.1468, 19.9706, 0)),
        ((-0.1468, 19.9706, 0), (-9.9853, 0, -9.9853)),
        ((-9.9853, 0, 9.9853), (-0.1468, 19.9706, 0)),
        ((-0.1468, 19.9706, 0), (9.9853, 0, 9.9853)),
        ((9.9853, 0, 9.9853), (-9.9853, 0, 9.9853)),
        ((-9.9853, 0, 9.9853), (-9.9853, 0, -9.9853)),
        ((9.9853, 0, -9.9853), (9.9853, 0, 9.9853)),
    ],
    "faces": [
        ((-9.9853, 0, -9.9853), (9.9853, 0, -9.9853), (9.9853, 0, 9.9853), (-9.9853, 0, 9.9853)),
        ((-9.9853, 0, -9.9853), (9.9853, 0, -9.9853), (-0.1468, 19.9706, 0)),
        ((9.9853, 0, -9.9853), (9.9853, 0, 9.9853), (-0.1468, 19.9706, 0)),
        ((9.9853, 0, 9.9853), (-9.9853, 0, 9.9853), (-0.1468, 19.9706, 0)),
        ((-9.9853, 0, 9.9853), (-9.9853, 0, -9.9853), (-0.1468, 19.9706, 0)),
    ],
    "scale": 1.0,
    "bob_speed": 0.0,
    "bob_amount": 0.0,
}