# `<PROJECT_NAME>` — Components of <container> (C4 level 3)

<!-- One per non-trivial service: the main parts inside one container and how requests move
     between them. Name the file after the container, e.g. docs/architecture/api.md. -->

```mermaid
C4Component
    title Components of <container>
    Container_Boundary(api, "<container>") {
        Component(routes, "<Routes>", "<technology>", "<what it does>")
        Component(core, "<Domain core>", "<technology>", "<the rules; depends on nothing else>")
        Component(store, "<Repository>", "<technology>", "<data access>")
    }
    Rel(routes, core, "<Calls>")
    Rel(store, core, "<Implements its ports>")
```
