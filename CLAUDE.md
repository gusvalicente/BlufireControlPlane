# Agent instructions for blufire-platform

Read SETUP.md first. It explains the architecture, every directory, how state flows, and the exact setup order.

Rules that matter most:
- Desired state lives in git (`platform.yaml`, `registry/`, `policies/`, `alerts/`). Never change Azure by hand;
  change the YAML and let `apply.yml` deploy it. Drift is detected and reported.
- Changes that match `policies/approvals.yaml` need Gus's approval. As an agent you can propose them, never approve.
- Never print, log or commit secret values. Logs identify people by Entra object ID only.
- Resource names follow the Naming table in `docs/runtime-config.md`, mirrored in
  `control-plane/src/blufire_cp/naming.py` and `tools/render_params.py`. Change all three together.
- Run before you push: `pytest control-plane tools/tests`, `ruff check control-plane`, `bicep build` on changed
  stacks, `npm run lint && npm run build` in `control-plane/ui`.
- No em dashes in any user-facing text.
