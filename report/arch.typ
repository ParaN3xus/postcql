#import "@preview/fletcher:0.5.8" as fletcher: diagram, edge, node
#import "colors.typ": *

#let overall-struc = move(dx: 0.8cm, diagram(
  // debug: true,
  node-corner-radius: 4pt,
  {
    let mix-with-white(c, amount: 90%) = {
      let channels = c.components().slice(0, 3)
      rgb(
        channels.at(0) * (100% - amount) + amount,
        channels.at(1) * (100% - amount) + amount,
        channels.at(2) * (100% - amount) + amount,
      )
    }
    let tint(c) = (stroke: c, fill: mix-with-white(c, amount: 90%), inset: 8pt)

    node(
      (0, 0),
      height: 3cm,
      width: 4cm,
      align(top, [
        Source Code
        #image("assets/image-magick.svg", width: 1.6cm)
      ]),
      shape: rect,
      ..tint(chart-primary),
      name: <src>,
    )
    edge(<src>, <cqldb>, "->", image("assets/ql.svg", width: 0.5cm))
    node(
      (1, 0),
      height: 3cm,
      width: 4.2cm,
      align(top, {
        [CodeQL Database]
        image("assets/codeql.png", width: 1.5cm)
      }),
      shape: rect,
      ..tint(chart-secondary),
      name: <cqldb>,
    )
    edge(
      <cqldb>,
      <alerts>,
      "->",
      {
        align(center, {
          image("assets/ql.svg", width: 0.5cm)
          text(0.7em, `cpp-security-extended`)
          v(0.8em)
        })
      },
      label-fill: false,
      label-side: center,
    )
    node(
      (2, 0),
      height: 3cm,
      align(top, {
        [CodeQL Alerts]
        v(-5pt)
        stack(
          dir: ttb,
          spacing: 5pt,
          ..(
            rect(radius: 4pt, height: 10pt, width: 100%, ..tint(chart-secondary.lighten(12%)), {
              move(dy: -9pt, "...")
            }),
          )
            * 4,
        )
      }),
      shape: rect,
      ..tint(chart-secondary),
      name: <alerts>,
    )

    node(
      (2, 1),
      height: 2.8cm,
      defocus: -2569,
      shape: rect,
      ..tint(chart-agent),
      {
        `agents.Agent`
        image("assets/chatgpt.svg", width: 1cm)
      },
      name: <agent>,
    )

    node(
      (2, 2),
      height: 2.8cm,
      { box(width: 6cm) },
    )
    node(
      (rel: (0mm, 10mm), to: (1, 1)),
      width: 4.2cm,
      shape: rect,
      ..tint(chart-agent),
      `read_source(...)`,
      name: <readsrc>,
    )
    node(
      (rel: (0mm, 0mm), to: (1, 1)),
      width: 4.2cm,
      shape: rect,
      ..tint(chart-agent),
      `search_source(...)`,
      name: <searchsrc>,
    )
    node(
      (rel: (0mm, -10mm), to: (1, 1)),
      width: 4.2cm,
      shape: rect,
      ..tint(chart-agent),
      `mcp-language-server`,
      name: <mcp>,
    )

    node(
      (rel: (0mm, -10mm), to: (0, 1)),
      shape: rect,
      ..tint(chart-secondary),
      `clangd`,
      name: <lsp>,
    )
    edge(<src>, <lsp>, "->")
    edge(<src>, <readsrc>, "->", corner: left)
    edge(<src>, <searchsrc>, "->", corner: left)
    edge(<lsp>, <mcp>, "->")

    edge(<readsrc>, (rel: (0mm, 10mm), to: <agent>), "->")
    edge(<searchsrc>, <agent>, "->")
    edge(<mcp>, (rel: (0mm, -10mm), to: <agent>), "->")

    edge(<alerts>, <agent>, "->")

    node(
      (1, 2),
      width: 4.2cm,
      [
        `submit_triage_report`
      ],
      shape: rect,
      ..tint(chart-agent),
      name: <submit>,
    )
    edge(<agent>, <submit>, "->", corner: right)

    node(
      (0, 2),
      width: 4cm,
      align(center, {
        [Alert Triage Reports]
        range(7)
          .map(x => {
            place(
              dx: (-x) * -0.3cm + 0.3cm,
              dy: (20 - x) * 0.02cm,
              box(fill: white, image("assets/example-report.pdf", width: 1cm, page: (10 - x))),
            )
          })
          .join()
        v(1.8cm)
      }),
      shape: rect,
      ..tint(chart-output),
      name: <report>,
    )
    edge(<submit>, <report>, "->")
  },
))


#set page(width: auto, height: auto, margin: (x: 0pt, y: 20pt), fill: rgb(0, 0, 0, 0))
#overall-struc
