"""Cabinet bounding boxes — Python twin of cabinetBox() in static/index.html.
Run: ./venv/bin/python test_cabinet_box.py"""
import json

WALL = (250, 600, 2850, 1120)      # viewBox of #wall-map in static/index.html


def cabinet_box(motors, n):
    pts = [(m["x"], m["y"]) for m in motors if m["cabinet"] == n]
    if not pts:
        return None
    x = min(p[0] for p in pts)
    y = min(p[1] for p in pts)
    return (x, y, max(p[0] for p in pts) - x, max(p[1] for p in pts) - y)


motors = json.load(open("motor_map.json"))["motors"]
cabs = sorted({m["cabinet"] for m in motors})
assert cabs == list(range(1, 12)), cabs
for n in cabs:
    x, y, w, h = cabinet_box(motors, n)
    assert w > 0 or h > 0, (n, w, h)          # Cab 11 is a straight run: h == 0 is fine
    for m in motors:
        if m["cabinet"] == n:
            assert x <= m["x"] <= x + w and y <= m["y"] <= y + h, (n, m["motor"])
    assert WALL[0] <= x and x + w <= WALL[0] + WALL[2], (n, x, w)
    assert WALL[1] <= y and y + h <= WALL[1] + WALL[3], (n, y, h)
assert cabinet_box(motors, 99) is None
# The JS must use the same source: the rule text lives in index.html.
html = open("static/index.html").read()
assert "function cabinetBox(inv, n)" in html
assert "trivision.tab" in html
assert "body.touch" in html and "plabel" in html   # touch mode + prism labels
print("ok")
