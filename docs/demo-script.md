# Demo GIF recording script

Exact command sequence for recording `docs/demo.gif`. Record inside the
repohealth repository (or any repository with a few months of history —
the output is more interesting).

## Sequence

```bash
repohealth scan .
# pause ~2s
repohealth report .
# pause ~2s
repohealth hotspots . --top 5
# pause ~2s, then stop the recording
```

## Recording tips

- Terminal window about **100 columns** wide (tables fit without
  wrapping) and ~30 rows.
- Use a **dark theme** with good contrast; the Rich colors are designed
  for dark backgrounds.
- Type (or replay) each command, wait for the output, then pause **~2
  seconds** before the next one so viewers can read the tables.
- Keep the GIF under ~30 seconds; loop-friendly endings look best.
- Suggested tools: [vhs](https://github.com/charmbracelet/vhs) (scripted,
  reproducible — see `docs/demo.tape`), asciinema + agg, or peek.

## Generating with vhs

```bash
vhs docs/demo.tape   # writes docs/demo.gif
```
