#import "@preview/zebraw:0.6.1": *
#import "@preview/cmarker:0.1.8": render

#let workspace-dir = str(sys.inputs.at("workspace_dir", default: "/work"))


#let source-segment(
  workspace,
  relpath,
  from,
  to,
  highlight-from,
  highlight-to,
) = {
  let fullpath = workspace + "/source/" + relpath
  let all-lines = read(fullpath).split("\n")
  let total = all-lines.len()

  from = from - 1
  let start0 = calc.clamp(calc.min(from, to), 0, total)
  let end0 = calc.clamp(calc.max(from, to), 0, total)

  let lines = all-lines.slice(start0, end0)

  // rm common indent
  let nonempty = lines.filter(line => line.trim() != "")
  let indents = nonempty.map(line => {
    let chars = line.clusters()
    let n = 0
    for ch in chars {
      if ch == " " or ch == "\t" {
        n += 1
      } else {
        break
      }
    }
    n
  })

  let common-indent = if indents.len() == 0 {
    0
  } else {
    indents.fold(indents.at(0), (a, b) => if a < b { a } else { b })
  }

  let stripped = lines.map(line => {
    let chars = line.clusters()
    if chars.len() <= common-indent {
      ""
    } else {
      chars.slice(common-indent).join()
    }
  })

  let hstart0 = calc.clamp(calc.min(highlight-from, highlight-to), 0, total)
  let hend0 = calc.clamp(calc.max(highlight-from, highlight-to), 0, total)

  let vis-hstart = calc.max(hstart0, start0)
  let vis-hend = calc.min(hend0, end0)

  let highlight-lines = if vis-hstart > vis-hend {
    ()
  } else if vis-hstart == vis-hend {
    (vis-hend - start0,)
  } else {
    range(vis-hstart - start0, vis-hend - start0)
  }

  if (stripped == ()) {
    panic(relpath)
  }

  link(fullpath, raw(relpath))

  zebraw(
    raw(
      block: true,
      lang: relpath.split(".").last(),
      stripped.join("\n"),
    ),
    numbering-offset: start0,
    highlight-color: red.lighten(80%),
    highlight-lines: highlight-lines,
  )
}

#let render-cql-severity(severity) = {
  if severity == "error" {
    return strong(text(red)[ERROR])
  }
  if severity == "warning" {
    return strong(text(orange)[WARNING])
  }
  if severity == "recommendation" {
    return text(blue)[Recommendation]
  }
}

#let render-verdict(verdict) = {
  if verdict == "real" {
    return strong(text(red)[REAL])
  }
  if verdict == "false_positive" {
    return text(green)[False positive]
  }
  if verdict == "uncertain" {
    return strong(text(orange)[UNCERTAIN])
  }
}

#let render-severity(severity) = {
  if severity == "critical" {
    return strong(text(red)[CRITICAL])
  }
  if severity == "high" {
    return strong(text(orange)[HIGH])
  }
  if severity == "medium" {
    return strong(text(yellow.darken(20%))[MEDIUM])
  }
  if severity == "low" {
    return text(blue)[LOW]
  }
}

#let is-noneish(value) = {
  if type(value) == str {
    value.trim() == "none"
  } else {
    value == none
  }
}

#let has-path-items(value) = {
  type(value) == array and value.len() > 0
}

#let has-validation-steps(value) = {
  type(value) == array and value.len() > 0 and "message" in value.at(0) and "evidence" in value.at(0)
}

#let render-path-items(items) = {
  if not has-path-items(items) {
    return
  }

  items
    .map(x => {
      let end-line = if x.end_line == none { x.start_line } else { x.end_line }
      render(x.message)
      source-segment(workspace-dir, x.file_path, x.start_line - 4, end-line + 4, x.start_line, end-line)
    })
    .join()
}

#let render-validation-steps(steps) = {
  if not has-validation-steps(steps) {
    return
  }

  steps
    .map(step => {
      render(step.message)
      if has-path-items(step.evidence) {
        render-path-items(step.evidence)
      }
    })
    .join()
}

#let single-report(report, heading-offset: 0) = {
  let raw = report.raw_row

  let h1(body) = heading(body, level: heading-offset + 1)
  let h2(body) = heading(body, level: heading-offset + 2)
  let h3(body) = heading(body, level: heading-offset + 3)

  h1[CodeQL Alert Info]
  [
    / Rule: #raw.rule_name
    / Severity: #render-cql-severity(raw.severity)
    / Rule description: #raw.rule_description
  ]
  // / Alert message: #raw.message \

  let start = raw.start.line
  let end = raw.end.line
  source-segment(workspace-dir, raw.relative_file_path, start - 8, end + 8, start, end)

  h1[Triage]

  [
    / Verdict: #render-verdict(report.verdict)
    / Severity: #render-severity(report.severity)
    / Explanation: #render(report.explanation)
  ]

  h1[Analysis]

  h2[CodeQL's Hypothesis]
  render(report.initial_hypothesis)

  h2[Hypothesis Validation]
  if has-validation-steps(report.hypothesis_validation) {
    render-validation-steps(report.hypothesis_validation)
  } else if has-path-items(report.hypothesis_validation) {
    render-path-items(report.hypothesis_validation)
  } else if not is-noneish(report.hypothesis_validation) {
    render(report.hypothesis_validation)
  }

  h2[Real-world Triggerability]
  render(report.triggerability)

  if has-path-items(report.trigger_path) {
    h3[Trigger Path]
    render-path-items(report.trigger_path)
  }

  if not is-noneish(report.impact) {
    h1[Impact]
    render(report.impact)
  }

  if not is-noneish(report.remediation) {
    h1[Remediation]
    render(report.remediation)
  }
}


#let common-styles(body) = {
  set par(justify: true)
  set page(numbering: "1")
  body
}
