@description('Microsoft Sentinel Log Analytics Workspace Name')
param WorkspaceName string

resource onboard 'Microsoft.OperationalInsights/workspaces/providers/onboardingStates@2024-03-01' = {
  name: '${WorkspaceName}/Microsoft.SecurityInsights/default'
  properties: {}
}
