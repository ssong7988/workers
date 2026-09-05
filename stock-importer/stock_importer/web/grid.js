// 화면에 보이는 표를 좌표로 복원한다.
//
// mable은 웹 HTS라 표가 <table>일 수도, 커스텀 div 그리드일 수도 있고 클래스
// 이름은 배포마다 바뀐다. 그래서 DOM 구조 대신 **사람이 보는 헤더 글자**를
// 앵커로 삼고, 셀의 화면 좌표로 행과 열을 되짚는다. <table>이면 그대로 통하고
// div 그리드여도 통한다.
//
// 돌려주는 셀은 문자열이 아니라 조각 배열이다. 종목명 칸에 'ETF' 배지가 따로
// 들어앉는 경우가 있어서, 어느 조각을 버릴지는 Python이 정한다.

(config) => {
  const SORT_MARKS = /[▲▼△▽↑↓⇅⇵ⓘ]/g;
  const ROW_TOLERANCE = 12;
  const MAX_CLIMB = 8;

  const norm = (text) =>
    (text || "").replace(/ /g, " ").replace(SORT_MARKS, "").trim();
  const key = (text) => norm(text).replace(/\s+/g, "");

  const headerKeys = new Set((config.headerLabels || []).map(key));
  const minMatches = config.minHeaderMatches || 4;

  // 잎사귀: 자식 엘리먼트가 없고, 화면에 보이고, 글자가 있는 것.
  const leaves = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  for (let node = walker.currentNode; node; node = walker.nextNode()) {
    if (node.childElementCount > 0) continue;
    const text = norm(node.textContent);
    if (!text || text.length > 80) continue;
    const rect = node.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    const style = window.getComputedStyle(node);
    if (style.visibility === "hidden" || style.opacity === "0") continue;
    leaves.push({
      node,
      text,
      key: key(text),
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
      cx: (rect.left + rect.right) / 2,
      cy: (rect.top + rect.bottom) / 2,
    });
  }

  // 같은 높이에 늘어선 헤더 글자들을 한 줄로 묶는다.
  const headerLeaves = leaves.filter((leaf) => headerKeys.has(leaf.key));
  const bands = [];
  for (const leaf of headerLeaves.slice().sort((a, b) => a.cy - b.cy)) {
    const band = bands[bands.length - 1];
    if (band && Math.abs(leaf.cy - band.cy) <= ROW_TOLERANCE) {
      band.items.push(leaf);
      band.cy = (band.cy * (band.items.length - 1) + leaf.cy) / band.items.length;
    } else {
      bands.push({ cy: leaf.cy, items: [leaf] });
    }
  }

  const commonAncestor = (nodes) => {
    let ancestor = nodes[0];
    for (const node of nodes.slice(1)) {
      while (ancestor && !ancestor.contains(node)) ancestor = ancestor.parentElement;
      if (!ancestor) return document.body;
    }
    return ancestor;
  };

  const candidates = [];
  for (const band of bands) {
    // 같은 라벨이 두 번 보이면 왼쪽 것만 쓴다.
    const seen = new Set();
    const columns = band.items
      .slice()
      .sort((a, b) => a.cx - b.cx)
      .filter((leaf) => (seen.has(leaf.key) ? false : (seen.add(leaf.key), true)));
    if (columns.length < minMatches) continue;

    const headerBottom = Math.max(...columns.map((column) => column.bottom));

    // 헤더 줄을 감싼 조상에서 시작해, 헤더 아래에 실제 글자가 있는 조상까지
    // 올라간다. 그것이 이 표의 몸통이다.
    let container = commonAncestor(columns.map((column) => column.node));
    let dataLeaves = [];
    for (let climb = 0; climb < MAX_CLIMB; climb += 1) {
      dataLeaves = leaves.filter(
        (leaf) =>
          leaf.top >= headerBottom - 2 &&
          !columns.includes(leaf) &&
          container.contains(leaf.node)
      );
      if (dataLeaves.length > 0 || !container.parentElement) break;
      container = container.parentElement;
    }
    if (dataLeaves.length === 0) continue;

    // 열 경계: 이웃한 헤더 사이의 가운데. 양 끝은 열어 둔다.
    const bounds = columns.map((column, index) => {
      const previous = columns[index - 1];
      const next = columns[index + 1];
      return {
        label: column.text,
        left: previous ? (previous.right + column.left) / 2 : -Infinity,
        right: next ? (column.right + next.left) / 2 : Infinity,
      };
    });
    const columnOf = (leaf) => {
      for (let index = 0; index < bounds.length; index += 1) {
        if (leaf.cx >= bounds[index].left && leaf.cx < bounds[index].right) return index;
      }
      return -1;
    };

    // 높이로 행을 되짚는다.
    const rows = [];
    let current = null;
    for (const leaf of dataLeaves.slice().sort((a, b) => a.cy - b.cy || a.cx - b.cx)) {
      if (!current || Math.abs(leaf.cy - current.cy) > ROW_TOLERANCE) {
        current = { cy: leaf.cy, cells: bounds.map(() => []) };
        rows.push(current);
      }
      const index = columnOf(leaf);
      if (index >= 0) current.cells[index].push(leaf.text);
    }

    const filled = rows
      .filter((row) => row.cells.some((cell) => cell.length > 0))
      .map((row) => row.cells);

    candidates.push({
      headers: bounds.map((bound) => bound.label),
      rows: filled,
      rowCount: filled.length,
      headerTop: Math.min(...columns.map((column) => column.top)),
      containerTag: container.tagName.toLowerCase(),
      containerClass: (container.className || "").toString().slice(0, 120),
    });
  }

  // 탭 라벨과 건수. 라벨과 숫자가 따로 그려질 수 있어 옆 칸도 본다.
  const tabs = [];
  for (const word of config.tabWords || []) {
    for (const leaf of leaves) {
      if (!leaf.key.startsWith(key(word))) continue;
      const inline = leaf.key.slice(key(word).length);
      let count = /^\d+$/.test(inline) ? Number(inline) : null;
      if (count === null) {
        const neighbour = leaves.find(
          (other) =>
            other !== leaf &&
            Math.abs(other.cy - leaf.cy) <= ROW_TOLERANCE &&
            other.left >= leaf.right - 2 &&
            other.left - leaf.right < 60 &&
            /^\d+$/.test(other.key)
        );
        if (neighbour) count = Number(neighbour.key);
      }
      tabs.push({ label: word, text: leaf.text, count });
      break;
    }
  }

  candidates.sort((a, b) => b.rowCount - a.rowCount);
  return {
    url: document.location.href,
    title: document.title,
    tabs,
    leafCount: leaves.length,
    candidates: candidates.slice(0, 4),
  };
};
