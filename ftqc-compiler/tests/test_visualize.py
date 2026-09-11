import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle
import pytest

from ftqc_patch_rotation.schedule import ScheduledOperation
from ftqc_patch_rotation.visualize import draw_schedule


def test_gate_shapes_labels_and_clearance(tmp_path, monkeypatch):
    schedule = tuple(ScheduledOperation(kind, (0,)) for kind in
                     ("h", "z", "folding", "icz", "s", "unfolding"))
    schedule += (ScheduledOperation("cz", (0, 1)),)
    monkeypatch.setattr(plt, "close", lambda *args: None)
    try:
        draw_schedule(schedule, 2, tmp_path / "gates.png")
        fig = plt.gcf()
        fig.canvas.draw()
        ax = fig.axes[0]
        boxes = [patch for patch in ax.patches if isinstance(patch, Rectangle)]
        labels = [text for text in ax.texts if text.get_text() in
                  {"H", "Z", "Fold", "iCZ", "S", "Unfold"}]
        assert len(boxes) == len(labels) == 6
        assert "CZ" not in [text.get_text() for text in ax.texts]
        assert len([p for p in ax.patches if isinstance(p, Circle)]) == 2
        previous = None
        for box, label in zip(boxes, labels):
            bounds = box.get_window_extent()
            text_bounds = label.get_window_extent()
            if len(label.get_text()) == 1:
                assert bounds.width == pytest.approx(bounds.height)
            else:
                assert bounds.width > bounds.height
            assert bounds.x0 < text_bounds.x0 < text_bounds.x1 < bounds.x1
            assert bounds.y0 < text_bounds.y0 < text_bounds.y1 < bounds.y1
            assert label.get_fontsize() > 6.5
            if previous is not None:
                assert previous.x1 < bounds.x0
            previous = bounds
    finally:
        monkeypatch.undo()
        plt.close("all")
