---
name: Flowchart
description: Optimised instructions for flowcharts.
category: preset
---
Create a well-structured flowchart that is easy to follow.

Node shapes:
- Rounded rectangle (rx/ry ≈ 8 px): Start and End
- Rectangle: Process / action step
- Diamond: Decision (Yes/No or True/False)
- Parallelogram: Input / Output

Guidelines:
- Draw connecting arrows using `<line>` or `<path>` with an arrowhead marker defined in `<defs>`.
- Label every node concisely (≤ 6 words per label).
- Label every decision branch (e.g., "Yes" / "No").
- Flow generally from top to bottom or left to right.
- Use colour to differentiate start/end from decision nodes.
- Align nodes on a consistent grid.
