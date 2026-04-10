#import "template.typ": common-styles, single-report

#let reports = json(bytes(sys.inputs.at("reports_json", default: "[]")))

#set document(title: "CodeQL Alert Triage Full Report")
#set heading(numbering: "1.")
#show: common-styles

#(
  reports
    .enumerate()
    .map(entry => {
      single-report(report, heading-offset: 1)
      pagebreak(weak: true)
    })
    .join()
)
