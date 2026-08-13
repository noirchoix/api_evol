# Analysis Model

The engine separates four evidence layers:

1. **Contract evidence** — canonical old/new API structures and classified semantic differences.
2. **Usage evidence** — source locations that structurally reference affected API paths or fields.
3. **Dependency evidence** — bounded reverse-import propagation from directly affected files.
4. **Validation evidence** — deterministic static gates and, when explicitly authorized, project lint/type/test/build outputs.

Patch generation never upgrades low-confidence usage evidence into a high-confidence automatic edit. Human approval is a separate gate from change detection.
