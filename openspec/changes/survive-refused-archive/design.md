# Design

`runner/runner.py:merge_path` runs `openspec archive <name> -y` without `check=True`, then checks
whether `openspec/changes/<name>` still exists. If it does, it sends ⚠️ with openspec's output and
the command to run by hand, skips the archive commit, and carries on. The code is already on `main`
at that point, so stopping would only leave the run half-finished.
