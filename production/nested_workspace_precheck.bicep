// Fail before anything is created when the workspace this install writes into
// does not exist.
//
// An ARM resource whose condition is false still SATISFIES a dependsOn, so
// `dependsOn: [Workspace]` is not a guard: with CreateWorkspace=false and a
// misspelled workspace name every resource that does not touch the workspace
// still gets created, and the customer is left with a half install (measured
// on this template, see progress/task_azure_0062).
//
// A guard has to READ the workspace. `existing` + an output that reads a
// property compiles to an inner-scope nested deployment whose expression is a
// reference() call, and reference() on a resource that is not there fails the
// deployment before the first resource is submitted. resourceId() alone would
// not do it - that is string arithmetic and succeeds for anything.
//
// The scope is passed by the caller so the same module guards both the
// same-resource-group and the cross-resource-group case.

@description('Log Analytics workspace that must already exist before the install starts.')
param WorkspaceName string

resource ws 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: WorkspaceName
}

// customerId is the workspace GUID. Reading it proves the workspace answers,
// not merely that a name could be spelled.
output customerId string = ws.properties.customerId
