"""
sort_easyocr_results.py

Takes the raw output of easyocr.Reader.readtext() and returns it reordered
into proper reading order: top-to-bottom by row, left-to-right within a row.

Why not just sort by (y_top, x_left)?
--------------------------------------
Because bounding boxes from OCR are noisy in height. A box that's taller
than its neighbors (due to a mis-detected glyph, an emote, a descender,
etc.) can have a smaller y_top than a box that's actually to its LEFT on
the same visual line. Sorting by y_top directly puts the tall box first,
even though it should come second, third, or wherever its x-position says
it belongs.

The fix: don't compare y_top values directly. Instead, decide "are these
two boxes on the same line?" by measuring how much they overlap vertically,
as a FRACTION of the shorter box's height. This scales naturally with font
size (no fixed pixel margin to tune per-image) and correctly handles a
tall box "swallowing" a shorter one that's on the same line.
"""

from typing import List, Tuple, Sequence


# ---------------------------------------------------------------------------
# STEP 1: Get clean (x_left, x_right, y_top, y_bottom) bounds out of whatever
# box format you have. EasyOCR gives 4 corner points:
#   [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
# This function works even if the points aren't perfectly axis-aligned
# (EasyOCR boxes are sometimes very slightly rotated), because it just takes
# the min/max over all 4 x's and all 4 y's.
# ---------------------------------------------------------------------------
def _box_bounds(box) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return min(xs), max(xs), min(ys), max(ys)


# ---------------------------------------------------------------------------
# STEP 2: The overlap-ratio check between two boxes.
# This is the core idea from earlier: overlap is measured as a fraction of
# the SHORTER box's height, not the taller one, not the average.
#
# Why the shorter box specifically? Picture a short box fully contained
# inside a tall box's vertical range (like box2 sitting inside box3's span
# from the earlier example). The intersection equals the short box's full
# height. Dividing by the short box's height gives ratio = 1.0 -> "yes,
# same row" -- correctly, since the short box's entire vertical extent is
# inside the tall box's extent.
#
# If we divided by the TALLER box's height instead, that same case would
# give a ratio well under 1.0, and a real same-line pair could fail to
# merge just because one box happened to be unusually tall.
# ---------------------------------------------------------------------------
def _vertical_overlap_ratio(bounds_a, bounds_b) -> float:
    _, _, a_top, a_bottom = bounds_a
    _, _, b_top, b_bottom = bounds_b

    intersection = min(a_bottom, b_bottom) - max(a_top, b_top)
    if intersection <= 0:
        return 0.0  # no vertical overlap at all

    a_height = a_bottom - a_top
    b_height = b_bottom - b_top
    shorter_height = min(a_height, b_height)

    if shorter_height <= 0:
        return 0.0  # degenerate box, avoid divide-by-zero

    return intersection / shorter_height


# ---------------------------------------------------------------------------
# STEP 3: Union-find (aka disjoint-set). This is what lets the "same row?"
# check chain transitively: if box A merges with box B, and box B merges
# with box C, then A, B, and C all end up in ONE group -- even though A and
# C might never have been checked as directly overlapping enough on their
# own.
#
# This is a textbook union-find with path compression (`find`) but no
# union-by-rank, since our box counts are small (dozens, not millions) --
# performance isn't a concern here, clarity is.
# ---------------------------------------------------------------------------
class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        # Walk up to the root, compressing the path as we go so future
        # lookups are faster (not that it matters much at this scale).
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        root_i, root_j = self.find(i), self.find(j)
        if root_i != root_j:
            self.parent[root_i] = root_j


# ---------------------------------------------------------------------------
# STEP 4: Build the rows.
#   1. Compute bounds for every box.
#   2. Check every pair of boxes; if their overlap ratio clears the
#      threshold, union them.
#   3. Collect boxes into their final groups (rows).
#   4. Sort the rows themselves by the row's average y-center, so rows
#      come out top-to-bottom.
#
# Returned as a list of (row_y_center, [indices_in_this_row]) tuples,
# already sorted top-to-bottom. The indices are NOT yet sorted left-to-right
# within the row -- that happens in the next step.
# ---------------------------------------------------------------------------
def cluster_into_rows(
    results: Sequence[tuple],
    overlap_threshold: float = 0.5,
) -> Tuple[List[Tuple[float, List[int]]], List[Tuple[float, float, float, float]]]:
    """
    results: EasyOCR-style list, where each element is (box, text, conf)
             or just (box, text) -- box is the 4-point polygon.
    overlap_threshold: 0-1. Higher = stricter (fewer merges, more likely to
             split a true line into two rows). Lower = looser (more merges,
             more likely to accidentally combine two real lines into one).
             0.5 is a reasonable starting point.
    """
    n = len(results)
    bounds = [_box_bounds(r[0]) for r in results]

    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if _vertical_overlap_ratio(bounds[i], bounds[j]) >= overlap_threshold:
                uf.union(i, j)

    groups = {}
    for i in range(n):
        root = uf.find(i)
        groups.setdefault(root, []).append(i)

    rows = []
    for idxs in groups.values():
        y_center = sum((bounds[i][2] + bounds[i][3]) / 2 for i in idxs) / len(idxs)
        rows.append((y_center, idxs))

    rows.sort(key=lambda row: row[0])  # top-to-bottom
    return rows, bounds


# ---------------------------------------------------------------------------
# OPTIONAL: a faster version of STEP 4 using a sweep-line approach instead
# of comparing every box to every other box.
#
# The brute-force cluster_into_rows() above checks all n*(n-1)/2 pairs,
# which is O(n^2). For a normal chat-log screenshot (tens to a couple
# hundred boxes) this is completely fine -- a few thousand cheap comparisons,
# sub-millisecond. Don't bother with this version unless you're processing
# very large box counts (many hundreds+ per image, or accumulating boxes
# across a long batch) and it's actually shown up as slow.
#
# The idea: two boxes can only merge if their y-ranges overlap at all. A box
# near the top of the image and a box near the bottom can never merge, so
# there's no point checking them against each other. Sorting by y_top and
# sweeping through lets us skip those impossible comparisons entirely.
#
# How it works:
#   1. Sort box indices by y_top.
#   2. Walk through them in that order, keeping an "active" list of boxes
#      that are still vertically "in play" (their y_bottom hasn't been
#      passed yet by the current sweep position).
#   3. For each new box, only compare it against what's currently active --
#      not the full set.
#   4. Before adding the new box to active, drop anything from active whose
#      y_bottom is already above the new box's y_top. Since we're sweeping
#      in increasing y_top order, once a box's bottom has been passed, it
#      cannot overlap this box or any future one -- so it's safe to retire.
#
# In a normal chat log, "active" stays small (usually 1-3 boxes: whatever's
# on the current line or two), so total work becomes roughly O(n log n)
# instead of O(n^2).
# ---------------------------------------------------------------------------
def cluster_into_rows_fast(
    results: Sequence[tuple],
    overlap_threshold: float = 0.5,
) -> Tuple[List[Tuple[float, List[int]]], List[Tuple[float, float, float, float]]]:
    n = len(results)
    bounds = [_box_bounds(r[0]) for r in results]

    # Process boxes in order of increasing y_top.
    order = sorted(range(n), key=lambda i: bounds[i][2])

    uf = _UnionFind(n)
    active: List[int] = []  # indices of boxes still possibly overlapping future ones

    for idx in order:
        top_i = bounds[idx][2]

        # Retire anything whose bottom is already above this box's top --
        # it can't overlap this box or anything that comes after it.
        active = [j for j in active if bounds[j][3] > top_i]

        # Only compare against what's still active, not the full list.
        for j in active:
            if _vertical_overlap_ratio(bounds[idx], bounds[j]) >= overlap_threshold:
                uf.union(idx, j)

        active.append(idx)

    groups = {}
    for i in range(n):
        root = uf.find(i)
        groups.setdefault(root, []).append(i)

    rows = []
    for idxs in groups.values():
        y_center = sum((bounds[i][2] + bounds[i][3]) / 2 for i in idxs) / len(idxs)
        rows.append((y_center, idxs))

    rows.sort(key=lambda row: row[0])
    return rows, bounds


# ---------------------------------------------------------------------------
# STEP 5: Put it all together. This is the function you actually call.
# Within each row, sort by x_left (bounds[i][0]) to get left-to-right order.
# ---------------------------------------------------------------------------
def sort_easyocr_results(
    results: Sequence[tuple],
    overlap_threshold: float = 0.5,
) -> List[tuple]:
    """
    Drop-in replacement ordering for easyocr.Reader.readtext() output.

    Example:
        import easyocr
        reader = easyocr.Reader(['en'])
        results = reader.readtext('screenshot.png')
        ordered = sort_easyocr_results(results)
        for box, text, conf in ordered:
            print(text)
    """
    rows, bounds = cluster_into_rows(results, overlap_threshold)

    ordered = []
    for _, idxs in rows:
        idxs_sorted = sorted(idxs, key=lambda i: bounds[i][0])  # x_left
        ordered.extend(results[i] for i in idxs_sorted)

    return ordered


# ---------------------------------------------------------------------------
# Optional debugging helper: print out what rows/merges happened, so you
# can see whether the threshold needs adjusting for your data.
# ---------------------------------------------------------------------------
def debug_print_rows(results: Sequence[tuple], overlap_threshold: float = 0.5) -> None:
    rows, bounds = cluster_into_rows(results, overlap_threshold)
    for row_num, (y_center, idxs) in enumerate(rows, start=1):
        idxs_sorted = sorted(idxs, key=lambda i: bounds[i][0])
        texts = [results[i][1] for i in idxs_sorted]
        print(f"Row {row_num} (y~{y_center:.0f}): {texts}")


# ---------------------------------------------------------------------------
# Convenience wrapper for the case where you already have two parallel
# lists instead of EasyOCR's combined (box, text, conf) tuples: one list of
# (x1, y1, x2, y2) rectangles, and one list of the corresponding text
# strings. Same algorithm as sort_easyocr_results, just adapted to that
# input shape.
# ---------------------------------------------------------------------------
def sort_chat_text(new_chat_pos, new_raw_text, overlap_threshold: float = 0.5):
    """
    new_chat_pos: list of (x1, y1, x2, y2) boxes
    new_raw_text: list of text strings, same length and order as new_chat_pos
                  (new_chat_pos[i] is the box for new_raw_text[i])
    returns: sorted_raw_text -- new_raw_text reordered top-to-bottom,
             left-to-right
    """
    n = len(new_chat_pos)
    if len(new_raw_text) != n:
        raise ValueError(
            f"new_chat_pos has {n} boxes but new_raw_text has "
            f"{len(new_raw_text)} strings -- they must match 1:1."
        )

    # (x1, y1, x2, y2) is already (x_left, y_top, x_right, y_bottom), so no
    # polygon conversion needed -- use the rects directly as bounds.
    bounds = new_chat_pos

    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            # reorder each box from (x1,y1,x2,y2) to (x_left,x_right,y_top,y_bottom)
            # to match what _vertical_overlap_ratio expects
            a = (bounds[i][0], bounds[i][2], bounds[i][1], bounds[i][3])
            b = (bounds[j][0], bounds[j][2], bounds[j][1], bounds[j][3])
            if _vertical_overlap_ratio(a, b) >= overlap_threshold:
                uf.union(i, j)

    groups = {}
    for i in range(n):
        root = uf.find(i)
        groups.setdefault(root, []).append(i)

    rows = []
    for idxs in groups.values():
        y_center = sum((bounds[i][1] + bounds[i][3]) / 2 for i in idxs) / len(idxs)
        rows.append((y_center, idxs))
    rows.sort(key=lambda row: row[0])  # top-to-bottom

    sorted_raw_text = []
    for _, idxs in rows:
        idxs_sorted = sorted(idxs, key=lambda i: bounds[i][0])  # x1, left-to-right
        sorted_raw_text.extend(new_raw_text[i] for i in idxs_sorted)

    return sorted_raw_text


if __name__ == "__main__":
    # Smoke test using your real bounding boxes (converted from [x1,y1,x2,y2]
    # rectangles to EasyOCR's 4-point polygon format).
    rects = [
        (2015, 1089, 2065, 1097),
        (2089, 1089, 2117, 1097),
        (1997, 1105, 2141, 1131),
        (2138, 1099, 2242, 1139),
        (1997, 1135, 2433, 1167),
        (1997, 1163, 2071, 1189),
        (1997, 1193, 2219, 1223),
        (2227, 1195, 2485, 1223),
        (1999, 1221, 2111, 1249),
    ]
    fake_texts = [f"box{i}" for i in range(len(rects))]

    fake_results = [
        ([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], text, 1.0)
        for (x1, y1, x2, y2), text in zip(rects, fake_texts)
    ]

    print("--- row breakdown ---")
    debug_print_rows(fake_results)

    print("\n--- final flat reading order ---")
    for box, text, conf in sort_easyocr_results(fake_results):
        print(text)