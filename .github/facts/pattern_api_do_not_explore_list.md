# API Do-Not-Explore Execution Rules

- Do not broad-scan unrelated modules when the prompt names exact target files.
- Do not create new modules/tables/migrations unless the prompt explicitly requires them.
- Do not create new test files if an existing module-level test file already covers the target area.
- Do not inspect fixtures beyond the minimum required to mirror an existing local test pattern.
- Do not change route registration when editing an already-registered module.
- Do not refactor nearby code during benchmark tasks; implement the smallest valid delta.

## Search Budget

- Read at most:
  - target route file
  - target schema file
  - target DAO file
  - one existing test file in same module
  - one existing DAO test file (if needed)
- If requirements are still ambiguous after these reads, ask one clarifying question instead of continuing exploration.

## Snippets

### Minimal-file checklist

```text
1) Read target schema + DAO
2) Read local route in same module
3) Read nearest existing tests
4) Implement smallest patch
5) Run focused errors/tests on touched files only
```

### Benchmark-safe scope guard

```python
ALLOWED_FILES = {
    "app/<module>/rest.py",
    "app/<module>/<module>_schema.py",
    "app/dao/<module>_dao.py",
    "tests/app/<module>/test_rest.py",
}
# If a file is outside this set, skip unless prompt explicitly asks for it.
```
