import threading

import pytest
from PIL import Image

from gif_compiler import color_count, frame_durations, list_images, render


def make_image(path, size=(32, 24), color=(255, 0, 0, 255), mode="RGBA"):
    Image.new(mode, size, color).save(path)
    return str(path)


def test_list_images_natural_sort_and_extensions(tmp_path):
    for name in ("frame_10.PNG", "frame_2.png", "frame_1.PnG"):
        make_image(tmp_path / name)
    (tmp_path / "notes.txt").write_text("not an image")

    assert [p.rsplit("\\", 1)[-1] for p in list_images(tmp_path)] == [
        "frame_1.PnG", "frame_2.png", "frame_10.PNG"
    ]


def test_color_count_reference_values():
    for slider, expected in ((0, 256), (25, 256), (26, 252), (50, 160),
                             (75, 64), (76, 63), (100, 16)):
        assert color_count(slider) == expected


def test_frame_durations_reference_values():
    durations = frame_durations(24, 48)
    assert sum(durations) == 2000
    assert all(duration >= 20 for duration in durations)
    assert frame_durations(50, 50) == [20] * 50


@pytest.mark.parametrize("slider", [0, 100])
def test_rgba_sequence_renders(tmp_path, slider):
    paths = [make_image(tmp_path / f"rgba_{i}.png", color=color)
             for i, color in enumerate(((255, 0, 0, 120), (0, 0, 255, 200)))]
    output = str(tmp_path / f"rgba_{slider}.gif")

    render(paths, output, fps=10, slider=slider)

    with Image.open(output) as rendered:
        assert rendered.n_frames == 2


def test_mixed_size_sequence_uses_first_frame_dimensions(tmp_path):
    paths = [make_image(tmp_path / "frame_1.png", (40, 30)),
             make_image(tmp_path / "frame_2.png", (20, 50))]
    output = str(tmp_path / "mixed.gif")

    render(paths, output, fps=10, slider=50)

    with Image.open(output) as rendered:
        assert rendered.size == (40, 30)
        assert rendered.n_frames == 2


def test_cancel_mid_render_leaves_no_output_or_temp(tmp_path):
    paths = [make_image(tmp_path / f"frame_{i}.png", color=(i * 50, 0, 0, 255))
             for i in range(3)]
    output = str(tmp_path / "cancel.gif")
    cancel = threading.Event()

    def stop_after_first_frame(done, total):
        if done == 1:
            cancel.set()

    with pytest.raises(InterruptedError):
        render(paths, output, fps=10, slider=50, progress=stop_after_first_frame,
               cancel=cancel)

    assert not (tmp_path / "cancel.gif").exists()
    assert not (tmp_path / "cancel.gif.tmp").exists()


def test_corrupt_file_raises_without_temp(tmp_path):
    valid = make_image(tmp_path / "frame_1.png")
    corrupt = tmp_path / "frame_2.png"
    corrupt.write_bytes(b"not a valid image")
    output = str(tmp_path / "corrupt.gif")

    with pytest.raises(Exception):
        render([valid, str(corrupt)], output, fps=10, slider=50)

    assert not (tmp_path / "corrupt.gif.tmp").exists()


def test_one_image_renders_scaled_with_aspect_ratio(tmp_path):
    path = make_image(tmp_path / "only.png", size=(80, 40))
    output = str(tmp_path / "single.gif")

    render([path], output, fps=10, slider=50, max_width=40)

    with Image.open(output) as rendered:
        assert rendered.size == (40, 20)
        assert rendered.n_frames == 1
