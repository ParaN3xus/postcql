#import "template.typ": common-styles, single-report, zebraw

#let report = json(bytes(sys.inputs.at("report_json", default: read("single-example.json"))))
// #let report = json(bytes(sys.inputs.at(
//   "report_json",
//   default: read("/work/results/analyze-all-20260410-161338Z/54/report.json"),
// )))


#set document(title: "CodeQL Alert Triage Report #" + str(report.raw_row.row_index))
#set heading(numbering: "1.")
#show: common-styles

#title()


#single-report(report)
