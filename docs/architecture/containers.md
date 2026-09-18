# `tokelo` — Containers (C4 level 2)

<!-- The deployable pieces inside the system box, and how they talk: each app, service and data
     store, with its technology. Required, like the context diagram. A non-trivial service also
     gets a component diagram (level 3): copy docs/architecture/component.template.md. -->

```mermaid
C4Container
    title Containers: tokelo
    Person(user, "<Primary user>")
    System_Boundary(system, "tokelo") {
        Container(web, "<Web app>", "<technology>", "<what it does>")
        Container(api, "<API>", "<technology>", "<what it does>")
        ContainerDb(db, "<Database>", "<technology>", "<what it stores>")
    }
    Rel(user, web, "<Uses>", "HTTPS")
    Rel(web, api, "<Calls>", "JSON/HTTPS")
    Rel(api, db, "<Reads and writes>", "<protocol>")
```
