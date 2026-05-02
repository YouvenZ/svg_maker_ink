---
name: Isometric 3D
description: Isometric perspective with 30-degree grid alignment.
category: style
---
Use isometric 3D perspective throughout.

- All receding edges are drawn at exactly 30° above horizontal.
- Top faces, left faces, and right faces each use a distinct shade of the same colour family.
- Top face = lightest, right face = mid tone, left face = darkest.
- Use `transform="rotate(-30)"` and skew transforms to align elements to the isometric grid.
- Avoid perspective distortion — all parallel edges remain parallel.
- Ground shadows or environment elements add realism.
