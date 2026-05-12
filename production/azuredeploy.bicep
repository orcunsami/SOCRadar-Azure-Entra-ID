metadata title = 'SOCRadar Entra ID Integration for Microsoft Sentinel'
metadata description = 'Pulls leaked employee credentials from SOCRadar (Botnet, PII Exposure, VIP Protection) and takes automated remediation actions in Microsoft Entra ID. Logs to Microsoft Sentinel custom tables.'
metadata version = '1.0.0'
metadata author = 'SOCRadar'
metadata lastUpdateTime = '2026-03-26T00:00:00.000Z'

extension microsoftGraphV1_0

@description('Microsoft Sentinel Log Analytics Workspace Name')
param WorkspaceName string

@description('Location/region of the Log Analytics workspace (e.g. northeurope). Leave empty to use the deployment resource group’s location.')
param WorkspaceLocation string = ''

@description('Resource group of the Log Analytics workspace. Leave empty to use the current deployment resource group (default — same RG as Function App).')
param WorkspaceResourceGroup string = ''

@description('Create a new Log Analytics workspace with WorkspaceName (default: true). Set to false ONLY if you already have an existing workspace you want to use. Only valid when WorkspaceResourceGroup is empty (same RG as deployment). Sentinel will be onboarded automatically on the created/existing workspace.')
param CreateWorkspace bool = true

@description('SOCRadar Platform API Key (used for Botnet, PII Exposure, VIP Protection sources)')
@secure()
param SocradarApiKey string

@description('SOCRadar Company ID')
param SocradarCompanyId string

@description('SOCRadar Platform Base URL')
param SocradarBaseUrl string = 'https://platform.socradar.com'

@description('Create the App Registration inline during deployment (default: true). When true, an App Registration is created with FIC binding to the Function App UAMI — zero manual setup. Set false to use an existing App Registration (provide EntraIdClientId).')
param CreateAppRegistration bool = true

@description('Grant admin consent to the Microsoft Graph application permissions during deployment (default: false). When true, deployment also grants admin consent — fully zero-touch. REQUIRES the deploying user to hold one of these Microsoft Entra ID directory roles: Cloud Application Administrator, Application Administrator, or Privileged Role Administrator. If the deployer is only a subscription Owner without AAD admin role, leave this false and grant consent via Portal (1-click) after deploy.')
param GrantAdminConsent bool = false

@description('Existing App Registration Client ID (appId). Leave empty when CreateAppRegistration=true — a new App Reg will be created and its appId used automatically.')
param EntraIdClientId string = ''

@description('Comma-separated Microsoft Entra ID Tenant IDs to query for compromised users. The first tenant in the list is the primary one where the multi-tenant App Registration and the UAMI Federated Identity Credential live. Additional tenants must consent the same App Registration (signInAudience=AzureADMultipleOrgs). For single-tenant deployments, leave this empty and set EntraIdTenantId instead.')
param EntraIdTenantIds string = ''

@description('Single Entra ID Tenant ID. Used when EntraIdTenantIds is empty. Leave empty to auto-detect the current subscription tenant (single-tenant default). Set explicitly only for cross-tenant deployments.')
param EntraIdTenantId string = ''

@description('Entra ID Security Group ID for compromised users (required if EnableAddToGroup=true)')
param SecurityGroupId string = ''

@description('Enable Botnet Data v2 source')
param EnableBotnetSource bool = true

@description('Enable PII Exposure v2 source')
param EnablePiiSource bool = true

@description('Enable VIP Protection v2 source (UNVERIFIED: endpoint not in official API documentation)')
param EnableVipSource bool = false

@description('Look up each leaked identity in Microsoft Entra ID before taking actions. Requires User.Read.All. If false, User.Read.All becomes optional and the app only fetches SOCRadar data and writes to Log Analytics.')
param EnableUserLookup bool = true

@description('Revoke all active sign-in sessions for matched users. Requires EnableUserLookup=true and User.RevokeSessions.All.')
param EnableRevokeSession bool = true

@description('Add compromised users to a quarantine security group (requires SecurityGroupId to be set). Default false because most customers do not have a pre-existing quarantine group.')
param EnableAddToGroup bool = false

@description('Remove matched users from the security group. Requires EnableUserLookup=true, GroupMember.ReadWrite.All, and SecurityGroupId.')
param EnableRemoveFromGroup bool = false

@description('Force password change at next sign-in for matched users. Requires EnableUserLookup=true and User-PasswordProfile.ReadWrite.All.')
param EnablePasswordChange bool = false

@description('Disable matched user accounts. Requires EnableUserLookup=true and User.EnableDisableAccount.All. High impact; use with caution.')
param EnableDisableAccount bool = false

@description('Re-enable previously disabled accounts. Requires EnableUserLookup=true and User.EnableDisableAccount.All.')
param EnableEnableAccount bool = false

@description('Delete all non-password authentication methods (Microsoft Authenticator, phone, FIDO2, software OATH, Windows Hello, email, TAP) to force MFA re-registration at next sign-in. Works on all Entra ID tiers. Requires EnableUserLookup=true and UserAuthenticationMethod.ReadWrite.All. HIGH IMPACT — off by default.')
param EnableForceMfaReregistration bool = false

@description('Confirm matched users as compromised in Identity Protection. Requires EnableUserLookup=true, IdentityRiskyUser.ReadWrite.All, and Entra ID P1/P2 licensing.')
param EnableConfirmRisky bool = false

@description('Validate leaked credentials via ROPC (Resource Owner Password Credentials). Only possible with plaintext passwords. Requires Allow public client flows on the App Registration. Microsoft discourages ROPC in production.')
param EnableROPC bool = false

@description('Create Microsoft Sentinel incidents for compromised accounts')
param EnableCreateIncident bool = false

@description('Automatically resolve SOCRadar alarms when compromised user is found in Entra ID')
param EnableResolveAlarm bool = false

@description('Write plaintext passwords to Log Analytics tables. By default only password_present/masked fields are stored. Enable only if your security policy requires it.')
param EnableLogPlaintextPassword bool = false

@description('How often to check for new leaked credentials (1-24 hours)')
@minValue(1)
@maxValue(24)
param PollingIntervalHours int = 6

@description('Fallback: minutes of history to fetch on first run if InitialStartDate is empty. Default 43200 = 30 days.')
@minValue(0)
@maxValue(525600)
param InitialLookbackMinutes int = 43200

@description('Optional date (YYYY-MM-DD format, e.g. 2026-04-01) for the first fetch. Takes priority over InitialLookbackMinutes. Leave empty to use the lookback window. Not a number of minutes — use date format only.')
param InitialStartDate string = ''

@description('Max pages fetched per source per timer run (page size 100). Default 50 covers most customers. Raise to 100-200 for large backlog imports; keep 50 for steady-state low-volume.')
@minValue(1)
@maxValue(1000)
param MaxPagesPerRun int = 50

@description('Run function immediately on Function App start, in addition to the timer schedule. Default true (recommended for first deploy verification). Set false if you only want scheduled runs.')
param RunOnStartup bool = true

var functionAppName = 'socradar-entraid-${uniqueString(resourceGroup().id)}'
var managedIdentityName = 'SOCRadar-EntraID-MI'
var hostingPlanName = 'SOCRadar-EntraID-Plan'
var storageAccountName = take('srentraid${uniqueString(resourceGroup().id)}', 24)
var tableName = 'EntraIDState'
var appInsightsName = 'socradar-entraid-ai-${uniqueString(resourceGroup().id)}'
var StorageTableDataContributorRoleId = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
var WebsiteContributorRoleId = 'de139f84-1756-47ae-9be6-808fbbe84772'
var MonitoringMetricsPublisherRoleId = '3913510d-42f4-4e42-8a64-420c390055eb'
var workspaceResourceId = (empty(WorkspaceResourceGroup)
  ? Workspace.id
  : resourceId(WorkspaceResourceGroup, 'Microsoft.OperationalInsights/workspaces', WorkspaceName))
var pollingSchedule = '0 0 */${string(PollingIntervalHours)} * * *'
var dcrName = 'socradar-ei-dcr-${uniqueString(resourceGroup().id)}'

resource Workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = if (CreateWorkspace && empty(WorkspaceResourceGroup)) {
  name: WorkspaceName
  location: (empty(WorkspaceLocation) ? resourceGroup().location : WorkspaceLocation)
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: resourceGroup().location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
  }
}

resource storageAccountName_default 'Microsoft.Storage/storageAccounts/tableServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource storageAccountName_default_table 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  parent: storageAccountName_default
  name: tableName
}

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: resourceGroup().location
}

// ============================================================================
// Microsoft Graph: inline App Registration + Service Principal + FIC binding
// Eliminates the manual `az ad app federated-credential create` step.
// Customer permission required: Application Administrator role (typical for
// tenant admins deploying integrations). Falls back to existing App Reg
// when CreateAppRegistration=false.
// ============================================================================

var graphUniqueAppName = 'socradar-entraid-${uniqueString(resourceGroup().id)}'

resource appReg 'Microsoft.Graph/applications@v1.0' = if (CreateAppRegistration) {
  uniqueName: graphUniqueAppName
  displayName: 'SOCRadar Entra ID Integration'
  signInAudience: 'AzureADMyOrg'
  requiredResourceAccess: [
    {
      resourceAppId: '00000003-0000-0000-c000-000000000000' // Microsoft Graph
      resourceAccess: [
        { id: 'df021288-bdef-4463-88db-98f22de89214', type: 'Role' }    // User.Read.All
        { id: '77f3a031-c388-4f99-b373-dc68676a979e', type: 'Role' }    // User.RevokeSessions.All
        { id: 'dbaae8cf-10b5-4b86-a4a1-f871c94c6695', type: 'Role' }    // GroupMember.ReadWrite.All
        { id: '3011c876-62b7-4ada-afa2-506cbbecc68c', type: 'Role' }    // User.EnableDisableAccount.All
        { id: 'cc117bb9-00cf-4eb8-b580-ea2a878fe8f7', type: 'Role' }    // User-PasswordProfile.ReadWrite.All
        { id: '656f6061-f9fe-4807-9708-6a2e0934df76', type: 'Role' }    // IdentityRiskyUser.ReadWrite.All
        { id: '50483e42-d915-4231-9639-7fdb7fd190e5', type: 'Role' }    // UserAuthenticationMethod.ReadWrite.All
      ]
    }
  ]
}

resource appSp 'Microsoft.Graph/servicePrincipals@v1.0' = if (CreateAppRegistration) {
  appId: appReg.appId
}

resource fic 'Microsoft.Graph/applications/federatedIdentityCredentials@v1.0' = if (CreateAppRegistration) {
  name: '${appReg.uniqueName}/socradar-entraid-uami'
  audiences: ['api://AzureADTokenExchange']
  issuer: 'https://login.microsoftonline.com/${tenant().tenantId}/v2.0'
  subject: managedIdentity.properties.principalId
}

// Admin consent automation: grant each Graph application permission to the
// app's service principal. Requires the deploying user to have
// AppRoleAssignment.ReadWrite.All (Application Administrator role provides this).
// Eliminates the "Grant admin consent" portal click.
resource graphSpRef 'Microsoft.Graph/servicePrincipals@v1.0' existing = {
  appId: '00000003-0000-0000-c000-000000000000'
}

var grantedAppRoleIds = [
  'df021288-bdef-4463-88db-98f22de89214'    // User.Read.All
  '77f3a031-c388-4f99-b373-dc68676a979e'    // User.RevokeSessions.All
  'dbaae8cf-10b5-4b86-a4a1-f871c94c6695'    // GroupMember.ReadWrite.All
  '3011c876-62b7-4ada-afa2-506cbbecc68c'    // User.EnableDisableAccount.All
  'cc117bb9-00cf-4eb8-b580-ea2a878fe8f7'    // User-PasswordProfile.ReadWrite.All
  '656f6061-f9fe-4807-9708-6a2e0934df76'    // IdentityRiskyUser.ReadWrite.All
  '50483e42-d915-4231-9639-7fdb7fd190e5'    // UserAuthenticationMethod.ReadWrite.All
]

resource adminConsentGrants 'Microsoft.Graph/appRoleAssignedTo@v1.0' = [for roleId in grantedAppRoleIds: if (CreateAppRegistration && GrantAdminConsent) {
  appRoleId: roleId
  principalId: appSp.id
  resourceId: graphSpRef.id
}]

// Resolved app client ID — either newly created or provided as parameter
var resolvedAppClientId = CreateAppRegistration ? appReg.appId : EntraIdClientId

resource hostingPlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: hostingPlanName
  location: resourceGroup().location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  kind: 'functionapp'
  properties: {
    reserved: true
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: resourceGroup().location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    RetentionInDays: 30
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: resourceGroup().location
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }
  properties: {
    serverFarmId: hostingPlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccountName};AccountKey=${listKeys(storageAccount.id,'2023-05-01').keys[0].value};EndpointSuffix=core.windows.net'
        }
        {
          name: 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccountName};AccountKey=${listKeys(storageAccount.id,'2023-05-01').keys[0].value};EndpointSuffix=core.windows.net'
        }
        {
          name: 'WEBSITE_CONTENTSHARE'
          value: functionAppName
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'AzureWebJobsFeatureFlags'
          value: 'EnableWorkerIndexing'
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: reference(appInsights.id, '2020-02-02').ConnectionString
        }
        {
          name: 'WEBSITE_RUN_FROM_PACKAGE'
          value: 'https://github.com/orcunsami/SOCRadar-Azure-Entra-ID/releases/download/v1.0.1/FunctionApp.zip'
        }
        {
          name: 'POLLING_SCHEDULE'
          value: pollingSchedule
        }
        {
          name: 'SOCRADAR_BASE_URL'
          value: SocradarBaseUrl
        }
        {
          name: 'SOCRADAR_API_KEY'
          value: SocradarApiKey
        }
        {
          name: 'SOCRADAR_COMPANY_ID'
          value: SocradarCompanyId
        }
        {
          name: 'ENTRA_TENANT_IDS'
          value: EntraIdTenantIds
        }
        {
          name: 'ENTRA_TENANT_ID'
          value: (empty(EntraIdTenantId) ? subscription().tenantId : EntraIdTenantId)
        }
        {
          name: 'ENTRA_CLIENT_ID'
          value: resolvedAppClientId
        }
        {
          name: 'SECURITY_GROUP_ID'
          value: SecurityGroupId
        }
        {
          name: 'ENABLE_BOTNET_SOURCE'
          value: string(EnableBotnetSource)
        }
        {
          name: 'ENABLE_PII_SOURCE'
          value: string(EnablePiiSource)
        }
        {
          name: 'ENABLE_VIP_SOURCE'
          value: string(EnableVipSource)
        }
        {
          name: 'ENABLE_USER_LOOKUP'
          value: string(EnableUserLookup)
        }
        {
          name: 'ENABLE_REVOKE_SESSION'
          value: string(EnableRevokeSession)
        }
        {
          name: 'ENABLE_ADD_TO_GROUP'
          value: string(EnableAddToGroup)
        }
        {
          name: 'ENABLE_REMOVE_FROM_GROUP'
          value: string(EnableRemoveFromGroup)
        }
        {
          name: 'ENABLE_PASSWORD_CHANGE'
          value: string(EnablePasswordChange)
        }
        {
          name: 'ENABLE_DISABLE_ACCOUNT'
          value: string(EnableDisableAccount)
        }
        {
          name: 'ENABLE_ENABLE_ACCOUNT'
          value: string(EnableEnableAccount)
        }
        {
          name: 'ENABLE_CONFIRM_RISKY'
          value: string(EnableConfirmRisky)
        }
        {
          name: 'ENABLE_FORCE_MFA_REREGISTRATION'
          value: string(EnableForceMfaReregistration)
        }
        {
          name: 'ENABLE_ROPC'
          value: string(EnableROPC)
        }
        {
          name: 'ENABLE_CREATE_INCIDENT'
          value: string(EnableCreateIncident)
        }
        {
          name: 'ENABLE_RESOLVE_ALARM'
          value: string(EnableResolveAlarm)
        }
        {
          name: 'ENABLE_LOG_PLAINTEXT_PASSWORD'
          value: string(EnableLogPlaintextPassword)
        }
        {
          name: 'INITIAL_LOOKBACK_MINUTES'
          value: string(InitialLookbackMinutes)
        }
        {
          name: 'INITIAL_START_DATE'
          value: InitialStartDate
        }
        {
          name: 'WORKSPACE_ID'
          value: reference(workspaceResourceId, '2023-09-01').customerId
        }
        {
          name: 'DCR_IMMUTABLE_ID'
          value: reference(dcr.id, '2023-03-11').immutableId
        }
        {
          name: 'DCR_ENDPOINT'
          value: reference(dcr.id, '2023-03-11').endpoints.logsIngestion
        }
        {
          name: 'WORKSPACE_NAME'
          value: WorkspaceName
        }
        {
          name: 'WORKSPACE_LOCATION'
          value: (empty(WorkspaceLocation) ? resourceGroup().location : WorkspaceLocation)
        }
        {
          name: 'WORKSPACE_RESOURCE_GROUP'
          value: (empty(WorkspaceResourceGroup) ? resourceGroup().name : WorkspaceResourceGroup)
        }
        {
          name: 'SUBSCRIPTION_ID'
          value: subscription().subscriptionId
        }
        {
          name: 'STORAGE_ACCOUNT_NAME'
          value: storageAccountName
        }
        {
          name: 'AZURE_CLIENT_ID'
          value: reference(managedIdentity.id, '2023-01-31').clientId
        }
        {
          name: 'MAX_PAGES_PER_RUN'
          value: string(MaxPagesPerRun)
        }
        {
          name: 'RUN_ON_STARTUP'
          value: string(RunOnStartup)
        }
      ]
    }
  }
  dependsOn: [
    storageAccountName_default_table
  ]
}

resource Microsoft_Storage_storageAccounts_storageAccountName_managedIdentityName_StorageTableDataContributorRoleId 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storageAccount
  name: guid(storageAccount.id, managedIdentityName, StorageTableDataContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      StorageTableDataContributorRoleId
    )
    principalId: reference(managedIdentity.id, '2023-01-31').principalId
    principalType: 'ServicePrincipal'
  }
}

resource Microsoft_Web_sites_functionAppName_managedIdentityName_WebsiteContributorRoleId 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: functionApp
  name: guid(functionApp.id, managedIdentityName, WebsiteContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', WebsiteContributorRoleId)
    principalId: reference(managedIdentity.id, '2023-01-31').principalId
    principalType: 'ServicePrincipal'
  }
}

resource WorkspaceName_SOCRadar_Botnet_CL 'Microsoft.OperationalInsights/workspaces/tables@2022-10-01' = {
  parent: Workspace
  name: 'SOCRadar_Botnet_CL'
  properties: {
    schema: {
      name: 'SOCRadar_Botnet_CL'
      columns: [
        {
          name: 'TimeGenerated'
          type: 'dateTime'
        }
        {
          name: 'email'
          type: 'string'
        }
        {
          name: 'url'
          type: 'string'
        }
        {
          name: 'device_ip'
          type: 'string'
        }
        {
          name: 'device_os'
          type: 'string'
        }
        {
          name: 'country'
          type: 'string'
        }
        {
          name: 'log_date'
          type: 'string'
        }
        {
          name: 'is_employee'
          type: 'boolean'
        }
        {
          name: 'source'
          type: 'string'
        }
        {
          name: 'alarm_id'
          type: 'int'
        }
        {
          name: 'password_present'
          type: 'boolean'
        }
        {
          name: 'password_masked'
          type: 'string'
        }
        {
          name: 'is_plaintext'
          type: 'boolean'
        }
        {
          name: 'password'
          type: 'string'
        }
        {
          name: 'entra_status'
          type: 'string'
        }
        {
          name: 'entra_tenant_id'
          type: 'string'
        }
        {
          name: 'entra_account_enabled'
          type: 'boolean'
        }
        {
          name: 'severity'
          type: 'string'
        }
        {
          name: 'actions_taken'
          type: 'dynamic'
        }
        {
          name: 'mfa_methods_deleted'
          type: 'int'
        }
        {
          name: 'mfa_methods_skipped'
          type: 'int'
        }
      ]
    }
    retentionInDays: 30
    plan: 'Analytics'
  }
}

resource WorkspaceName_SOCRadar_PII_CL 'Microsoft.OperationalInsights/workspaces/tables@2022-10-01' = {
  parent: Workspace
  name: 'SOCRadar_PII_CL'
  properties: {
    schema: {
      name: 'SOCRadar_PII_CL'
      columns: [
        {
          name: 'TimeGenerated'
          type: 'dateTime'
        }
        {
          name: 'email'
          type: 'string'
        }
        {
          name: 'source_name'
          type: 'string'
        }
        {
          name: 'breach_date'
          type: 'string'
        }
        {
          name: 'discovery_date'
          type: 'string'
        }
        {
          name: 'is_employee'
          type: 'boolean'
        }
        {
          name: 'source'
          type: 'string'
        }
        {
          name: 'alarm_id'
          type: 'int'
        }
        {
          name: 'password_present'
          type: 'boolean'
        }
        {
          name: 'password_masked'
          type: 'string'
        }
        {
          name: 'is_plaintext'
          type: 'boolean'
        }
        {
          name: 'password'
          type: 'string'
        }
        {
          name: 'entra_status'
          type: 'string'
        }
        {
          name: 'entra_tenant_id'
          type: 'string'
        }
        {
          name: 'entra_account_enabled'
          type: 'boolean'
        }
        {
          name: 'severity'
          type: 'string'
        }
        {
          name: 'actions_taken'
          type: 'dynamic'
        }
        {
          name: 'mfa_methods_deleted'
          type: 'int'
        }
        {
          name: 'mfa_methods_skipped'
          type: 'int'
        }
      ]
    }
    retentionInDays: 30
    plan: 'Analytics'
  }
}

resource WorkspaceName_SOCRadar_VIP_CL 'Microsoft.OperationalInsights/workspaces/tables@2022-10-01' = {
  parent: Workspace
  name: 'SOCRadar_VIP_CL'
  properties: {
    schema: {
      name: 'SOCRadar_VIP_CL'
      columns: [
        {
          name: 'TimeGenerated'
          type: 'dateTime'
        }
        {
          name: 'email'
          type: 'string'
        }
        {
          name: 'keyword'
          type: 'string'
        }
        {
          name: 'vip_name'
          type: 'string'
        }
        {
          name: 'status'
          type: 'string'
        }
        {
          name: 'discovery_date'
          type: 'string'
        }
        {
          name: 'source_name'
          type: 'string'
        }
        {
          name: 'is_employee'
          type: 'boolean'
        }
        {
          name: 'source'
          type: 'string'
        }
        {
          name: 'alarm_id'
          type: 'int'
        }
        {
          name: 'password_present'
          type: 'boolean'
        }
        {
          name: 'password_masked'
          type: 'string'
        }
        {
          name: 'is_plaintext'
          type: 'boolean'
        }
        {
          name: 'entra_status'
          type: 'string'
        }
        {
          name: 'entra_tenant_id'
          type: 'string'
        }
        {
          name: 'entra_account_enabled'
          type: 'boolean'
        }
        {
          name: 'severity'
          type: 'string'
        }
        {
          name: 'actions_taken'
          type: 'dynamic'
        }
      ]
    }
    retentionInDays: 30
    plan: 'Analytics'
  }
}

resource WorkspaceName_SOCRadar_EntraID_Audit_CL 'Microsoft.OperationalInsights/workspaces/tables@2022-10-01' = {
  parent: Workspace
  name: 'SOCRadar_EntraID_Audit_CL'
  properties: {
    schema: {
      name: 'SOCRadar_EntraID_Audit_CL'
      columns: [
        {
          name: 'TimeGenerated'
          type: 'dateTime'
        }
        {
          name: 'source'
          type: 'string'
        }
        {
          name: 'total_records'
          type: 'int'
        }
        {
          name: 'employee_records'
          type: 'int'
        }
        {
          name: 'found_count'
          type: 'int'
        }
        {
          name: 'not_found_count'
          type: 'int'
        }
        {
          name: 'actions_taken'
          type: 'int'
        }
        {
          name: 'error_count'
          type: 'int'
        }
        {
          name: 'duration_sec'
          type: 'real'
        }
        {
          name: 'event_type'
          type: 'string'
        }
        {
          name: 'tenant_id'
          type: 'string'
        }
        {
          name: 'details'
          type: 'string'
        }
        {
          name: 'aadsts_code'
          type: 'string'
        }
      ]
    }
    retentionInDays: 30
    plan: 'Analytics'
  }
}

resource dcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name: dcrName
  location: (empty(WorkspaceLocation) ? resourceGroup().location : WorkspaceLocation)
  kind: 'Direct'
  properties: {
    description: 'SOCRadar Entra ID Integration — Logs Ingestion API'
    streamDeclarations: {
      'Custom-SOCRadar_Botnet_CL': {
        columns: [
          {
            name: 'TimeGenerated'
            type: 'datetime'
          }
          {
            name: 'email'
            type: 'string'
          }
          {
            name: 'url'
            type: 'string'
          }
          {
            name: 'device_ip'
            type: 'string'
          }
          {
            name: 'device_os'
            type: 'string'
          }
          {
            name: 'country'
            type: 'string'
          }
          {
            name: 'log_date'
            type: 'string'
          }
          {
            name: 'is_employee'
            type: 'boolean'
          }
          {
            name: 'source'
            type: 'string'
          }
          {
            name: 'alarm_id'
            type: 'int'
          }
          {
            name: 'password_present'
            type: 'boolean'
          }
          {
            name: 'password_masked'
            type: 'string'
          }
          {
            name: 'is_plaintext'
            type: 'boolean'
          }
          {
            name: 'password'
            type: 'string'
          }
          {
            name: 'entra_status'
            type: 'string'
          }
          {
            name: 'entra_tenant_id'
            type: 'string'
          }
          {
            name: 'entra_account_enabled'
            type: 'boolean'
          }
          {
            name: 'severity'
            type: 'string'
          }
          {
            name: 'actions_taken'
            type: 'dynamic'
          }
          {
            name: 'mfa_methods_deleted'
            type: 'int'
          }
          {
            name: 'mfa_methods_skipped'
            type: 'int'
          }
        ]
      }
      'Custom-SOCRadar_PII_CL': {
        columns: [
          {
            name: 'TimeGenerated'
            type: 'datetime'
          }
          {
            name: 'email'
            type: 'string'
          }
          {
            name: 'source_name'
            type: 'string'
          }
          {
            name: 'breach_date'
            type: 'string'
          }
          {
            name: 'discovery_date'
            type: 'string'
          }
          {
            name: 'is_employee'
            type: 'boolean'
          }
          {
            name: 'source'
            type: 'string'
          }
          {
            name: 'alarm_id'
            type: 'int'
          }
          {
            name: 'password_present'
            type: 'boolean'
          }
          {
            name: 'password_masked'
            type: 'string'
          }
          {
            name: 'is_plaintext'
            type: 'boolean'
          }
          {
            name: 'password'
            type: 'string'
          }
          {
            name: 'entra_status'
            type: 'string'
          }
          {
            name: 'entra_tenant_id'
            type: 'string'
          }
          {
            name: 'entra_account_enabled'
            type: 'boolean'
          }
          {
            name: 'severity'
            type: 'string'
          }
          {
            name: 'actions_taken'
            type: 'dynamic'
          }
          {
            name: 'mfa_methods_deleted'
            type: 'int'
          }
          {
            name: 'mfa_methods_skipped'
            type: 'int'
          }
        ]
      }
      'Custom-SOCRadar_VIP_CL': {
        columns: [
          {
            name: 'TimeGenerated'
            type: 'datetime'
          }
          {
            name: 'email'
            type: 'string'
          }
          {
            name: 'keyword'
            type: 'string'
          }
          {
            name: 'vip_name'
            type: 'string'
          }
          {
            name: 'status'
            type: 'string'
          }
          {
            name: 'discovery_date'
            type: 'string'
          }
          {
            name: 'source_name'
            type: 'string'
          }
          {
            name: 'is_employee'
            type: 'boolean'
          }
          {
            name: 'source'
            type: 'string'
          }
          {
            name: 'alarm_id'
            type: 'int'
          }
          {
            name: 'password_present'
            type: 'boolean'
          }
          {
            name: 'password_masked'
            type: 'string'
          }
          {
            name: 'is_plaintext'
            type: 'boolean'
          }
          {
            name: 'entra_status'
            type: 'string'
          }
          {
            name: 'entra_tenant_id'
            type: 'string'
          }
          {
            name: 'entra_account_enabled'
            type: 'boolean'
          }
          {
            name: 'severity'
            type: 'string'
          }
          {
            name: 'actions_taken'
            type: 'dynamic'
          }
        ]
      }
      'Custom-SOCRadar_EntraID_Audit_CL': {
        columns: [
          {
            name: 'TimeGenerated'
            type: 'datetime'
          }
          {
            name: 'source'
            type: 'string'
          }
          {
            name: 'total_records'
            type: 'int'
          }
          {
            name: 'employee_records'
            type: 'int'
          }
          {
            name: 'found_count'
            type: 'int'
          }
          {
            name: 'not_found_count'
            type: 'int'
          }
          {
            name: 'actions_taken'
            type: 'int'
          }
          {
            name: 'error_count'
            type: 'int'
          }
          {
            name: 'duration_sec'
            type: 'real'
          }
          {
            name: 'event_type'
            type: 'string'
          }
          {
            name: 'tenant_id'
            type: 'string'
          }
          {
            name: 'details'
            type: 'string'
          }
          {
            name: 'aadsts_code'
            type: 'string'
          }
        ]
      }
    }
    destinations: {
      logAnalytics: [
        {
          name: 'lawDest'
          workspaceResourceId: workspaceResourceId
        }
      ]
    }
    dataFlows: [
      {
        streams: [
          'Custom-SOCRadar_Botnet_CL'
        ]
        destinations: [
          'lawDest'
        ]
        outputStream: 'Custom-SOCRadar_Botnet_CL'
      }
      {
        streams: [
          'Custom-SOCRadar_PII_CL'
        ]
        destinations: [
          'lawDest'
        ]
        outputStream: 'Custom-SOCRadar_PII_CL'
      }
      {
        streams: [
          'Custom-SOCRadar_VIP_CL'
        ]
        destinations: [
          'lawDest'
        ]
        outputStream: 'Custom-SOCRadar_VIP_CL'
      }
      {
        streams: [
          'Custom-SOCRadar_EntraID_Audit_CL'
        ]
        destinations: [
          'lawDest'
        ]
        outputStream: 'Custom-SOCRadar_EntraID_Audit_CL'
      }
    ]
  }
  dependsOn: [
    WorkspaceName_SOCRadar_Botnet_CL
    WorkspaceName_SOCRadar_PII_CL
    WorkspaceName_SOCRadar_VIP_CL
    WorkspaceName_SOCRadar_EntraID_Audit_CL
  ]
}

resource Microsoft_Insights_dataCollectionRules_dcrName_managedIdentityName_MonitoringMetricsPublisherRoleId 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: dcr
  name: guid(dcr.id, managedIdentityName, MonitoringMetricsPublisherRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      MonitoringMetricsPublisherRoleId
    )
    principalId: reference(managedIdentity.id, '2023-01-31').principalId
    principalType: 'ServicePrincipal'
  }
}

resource triggerFirstRun_id 'Microsoft.Resources/deploymentScripts@2020-10-01' = {
  name: 'triggerFirstRun-${uniqueString(resourceGroup().id)}'
  location: resourceGroup().location
  kind: 'AzureCLI'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }
  properties: {
    azCliVersion: '2.50.0'
    retentionInterval: 'PT1H'
    timeout: 'PT15M'
    scriptContent: 'sleep 30 && az functionapp restart --name $FA_NAME --resource-group $RG_NAME && echo \'Function App restarted\''
    environmentVariables: [
      {
        name: 'FA_NAME'
        value: functionAppName
      }
      {
        name: 'RG_NAME'
        value: resourceGroup().name
      }
    ]
  }
  dependsOn: [
    functionApp
    Microsoft_Web_sites_functionAppName_managedIdentityName_WebsiteContributorRoleId
  ]
}

resource WorkspaceName_Microsoft_SecurityInsights_default 'Microsoft.OperationalInsights/workspaces/providers/onboardingStates@2024-03-01' = if (empty(WorkspaceResourceGroup)) {
  name: '${WorkspaceName}/Microsoft.SecurityInsights/default'
  properties: {}
  dependsOn: [
    Workspace
  ]
}

module sentinel_onboard_id './nested_sentinel_onboard_id.bicep' = if (!empty(WorkspaceResourceGroup)) {
  name: 'sentinel-onboard-${uniqueString(resourceGroup().id)}'
  scope: resourceGroup(WorkspaceResourceGroup)
  params: {
    WorkspaceName: WorkspaceName
  }
}

resource id_SOCRadar_EntraID_Botnet_Workbook 'Microsoft.Insights/workbooks@2022-04-01' = {
  name: guid(resourceGroup().id, 'SOCRadar-EntraID-Botnet-Workbook')
  location: resourceGroup().location
  kind: 'shared'
  properties: {
    displayName: 'SOCRadar Entra ID — Botnet Data'
    serializedData: '{"version": "Notebook/1.0", "items": [{"type": 1, "content": {"json": "## SOCRadar Entra ID \\u2014 Botnet Data Dashboard\\nEmployee credentials found in botnet logs, enriched with Microsoft Entra ID lookup and remediation actions."}, "name": "header"}, {"type": 9, "content": {"version": "KqlParameterItem/1.0", "parameters": [{"id": "tenant-id-param", "version": "KqlParameterItem/1.0", "name": "TenantId", "label": "Entra ID Tenant", "type": 2, "isRequired": true, "value": "All", "typeSettings": {"additionalResourceOptions": [], "includeAll": false, "showDefault": false}, "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "query": "union isfuzzy=true SOCRadar_Botnet_CL\\n| where isnotempty(entra_tenant_id)\\n| distinct entra_tenant_id\\n| project value = entra_tenant_id, label = entra_tenant_id\\n| union (datatable(value:string, label:string)[\'All\',\'All\'])\\n| order by label asc"}]}, "name": "parameters - tenant"}, {"type": 1, "content": {"json": "---\\n### Overview"}, "name": "overview-header"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_Botnet_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| count\\n| project Count", "size": 4, "title": "Total Records", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "tiles", "tileSettings": {"titleContent": {"columnMatch": "Count", "formatter": 12, "formatOptions": {"palette": "auto"}}, "showBorder": false}}, "customWidth": "25", "name": "total-records"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_Botnet_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where entra_status == \\"found\\"\\n| count\\n| project Count", "size": 4, "title": "Found in Entra ID", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "tiles", "tileSettings": {"titleContent": {"columnMatch": "Count", "formatter": 12, "formatOptions": {"palette": "redBright"}}, "showBorder": false}}, "customWidth": "25", "name": "found-entra"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_Botnet_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where entra_status == \\"compromised\\"\\n| count\\n| project Count", "size": 4, "title": "Confirmed Compromised", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "tiles", "tileSettings": {"titleContent": {"columnMatch": "Count", "formatter": 12, "formatOptions": {"palette": "red"}}, "showBorder": false}}, "customWidth": "25", "name": "compromised"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_Botnet_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where password_present == true\\n| count\\n| project Count", "size": 4, "title": "With Password", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "tiles", "tileSettings": {"titleContent": {"columnMatch": "Count", "formatter": 12, "formatOptions": {"palette": "orange"}}, "showBorder": false}}, "customWidth": "25", "name": "with-password"}, {"type": 1, "content": {"json": "---\\n### Entra ID Status Distribution"}, "name": "status-header"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_Botnet_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| summarize Count=count() by entra_status\\n| order by Count desc", "size": 2, "title": "Entra ID Status", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "piechart"}, "customWidth": "50", "name": "entra-status-pie"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_Botnet_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where password_present == true\\n| summarize Count=count() by is_plaintext\\n| extend PasswordType = iff(is_plaintext == true, \\"Plaintext\\", \\"Masked\\")\\n| project PasswordType, Count", "size": 2, "title": "Password Type Distribution", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "piechart"}, "customWidth": "50", "name": "password-type-pie"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_Botnet_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| summarize Count=count() by country\\n| order by Count desc\\n| take 10", "size": 2, "title": "Top Countries", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "barchart"}, "customWidth": "50", "name": "top-countries"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_Botnet_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| summarize Count=count() by device_os\\n| order by Count desc\\n| take 10", "size": 2, "title": "Device OS Distribution", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "barchart"}, "customWidth": "50", "name": "device-os"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_Botnet_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| summarize Count=count() by bin(TimeGenerated, 1d)\\n| order by TimeGenerated asc", "size": 0, "title": "Records Over Time", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "timechart"}, "name": "records-timeline"}, {"type": 1, "content": {"json": "---\\n### Recent Records"}, "name": "recent-header"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_Botnet_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| project TimeGenerated, email, entra_status, password_present, is_plaintext, country, device_os, actions_taken\\n| order by TimeGenerated desc\\n| take 50", "size": 0, "title": "Recent Botnet Records", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "table"}, "name": "recent-records"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_Botnet_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where isnotempty(entra_tenant_id)\\n| extend src = case(Type == \'SOCRadar_Botnet_CL\', \'Botnet\', Type == \'SOCRadar_PII_CL\', \'PII\', Type == \'SOCRadar_VIP_CL\', \'VIP\', \'Other\')\\n| summarize Records=count(), Found=countif(entra_status == \'found\'), Compromised=countif(entra_status == \'compromised\') by entra_tenant_id, src\\n| order by Records desc", "size": 1, "title": "Tenant Breakdown", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "table"}, "name": "tenant-breakdown"}], "isLocked": false, "fallbackResourceIds": ["/subscriptions/{Subscription}/resourceGroups/{ResourceGroup}/providers/Microsoft.OperationalInsights/workspaces/{Workspace}"]}'
    version: '1.0'
    sourceId: (empty(WorkspaceResourceGroup)
      ? Workspace.id
      : resourceId(WorkspaceResourceGroup, 'Microsoft.OperationalInsights/workspaces', WorkspaceName))
    category: 'sentinel'
  }
}

resource id_SOCRadar_EntraID_PII_Workbook 'Microsoft.Insights/workbooks@2022-04-01' = {
  name: guid(resourceGroup().id, 'SOCRadar-EntraID-PII-Workbook')
  location: resourceGroup().location
  kind: 'shared'
  properties: {
    displayName: 'SOCRadar Entra ID — PII Exposure'
    serializedData: '{"version": "Notebook/1.0", "items": [{"type": 1, "content": {"json": "## SOCRadar Entra ID \\u2014 PII Exposure Dashboard\\nEmployee credentials found in PII data breaches, enriched with Microsoft Entra ID lookup and remediation actions."}, "name": "header"}, {"type": 9, "content": {"version": "KqlParameterItem/1.0", "parameters": [{"id": "tenant-id-param", "version": "KqlParameterItem/1.0", "name": "TenantId", "label": "Entra ID Tenant", "type": 2, "isRequired": true, "value": "All", "typeSettings": {"additionalResourceOptions": [], "includeAll": false, "showDefault": false}, "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "query": "union isfuzzy=true SOCRadar_PII_CL\\n| where isnotempty(entra_tenant_id)\\n| distinct entra_tenant_id\\n| project value = entra_tenant_id, label = entra_tenant_id\\n| union (datatable(value:string, label:string)[\'All\',\'All\'])\\n| order by label asc"}]}, "name": "parameters - tenant"}, {"type": 1, "content": {"json": "---\\n### Overview"}, "name": "overview-header"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_PII_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| count\\n| project Count", "size": 4, "title": "Total Records", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "tiles", "tileSettings": {"titleContent": {"columnMatch": "Count", "formatter": 12, "formatOptions": {"palette": "auto"}}, "showBorder": false}}, "customWidth": "25", "name": "total-records"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_PII_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where entra_status == \\"found\\"\\n| count\\n| project Count", "size": 4, "title": "Found in Entra ID", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "tiles", "tileSettings": {"titleContent": {"columnMatch": "Count", "formatter": 12, "formatOptions": {"palette": "redBright"}}, "showBorder": false}}, "customWidth": "25", "name": "found-entra"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_PII_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where entra_status == \\"compromised\\"\\n| count\\n| project Count", "size": 4, "title": "Confirmed Compromised", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "tiles", "tileSettings": {"titleContent": {"columnMatch": "Count", "formatter": 12, "formatOptions": {"palette": "red"}}, "showBorder": false}}, "customWidth": "25", "name": "compromised"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_PII_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where password_present == true\\n| count\\n| project Count", "size": 4, "title": "With Password", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "tiles", "tileSettings": {"titleContent": {"columnMatch": "Count", "formatter": 12, "formatOptions": {"palette": "orange"}}, "showBorder": false}}, "customWidth": "25", "name": "with-password"}, {"type": 1, "content": {"json": "---\\n### Breach Analysis"}, "name": "breach-header"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_PII_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| summarize Count=count() by entra_status\\n| order by Count desc", "size": 2, "title": "Entra ID Status", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "piechart"}, "customWidth": "50", "name": "entra-status-pie"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_PII_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| summarize Count=count() by source_name\\n| order by Count desc\\n| take 10", "size": 2, "title": "Top Breach Sources", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "barchart"}, "customWidth": "50", "name": "top-sources"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_PII_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where password_present == true\\n| summarize Count=count() by is_plaintext\\n| extend PasswordType = iff(is_plaintext == true, \\"Plaintext\\", \\"Masked\\")\\n| project PasswordType, Count", "size": 2, "title": "Password Type Distribution", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "piechart"}, "customWidth": "50", "name": "password-type-pie"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_PII_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where isnotempty(breach_date)\\n| summarize Count=count() by breach_date\\n| order by breach_date asc", "size": 0, "title": "Records by Breach Date", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "timechart"}, "customWidth": "50", "name": "breach-date-chart"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_PII_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| summarize Count=count() by bin(TimeGenerated, 1d)\\n| order by TimeGenerated asc", "size": 0, "title": "Discovery Over Time", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "timechart"}, "name": "discovery-timeline"}, {"type": 1, "content": {"json": "---\\n### Recent Records"}, "name": "recent-header"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_PII_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| project TimeGenerated, email, entra_status, password_present, is_plaintext, source_name, breach_date, actions_taken\\n| order by TimeGenerated desc\\n| take 50", "size": 0, "title": "Recent PII Records", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "table"}, "name": "recent-records"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_PII_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where isnotempty(entra_tenant_id)\\n| extend src = case(Type == \'SOCRadar_Botnet_CL\', \'Botnet\', Type == \'SOCRadar_PII_CL\', \'PII\', Type == \'SOCRadar_VIP_CL\', \'VIP\', \'Other\')\\n| summarize Records=count(), Found=countif(entra_status == \'found\'), Compromised=countif(entra_status == \'compromised\') by entra_tenant_id, src\\n| order by Records desc", "size": 1, "title": "Tenant Breakdown", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "table"}, "name": "tenant-breakdown"}], "isLocked": false, "fallbackResourceIds": ["/subscriptions/{Subscription}/resourceGroups/{ResourceGroup}/providers/Microsoft.OperationalInsights/workspaces/{Workspace}"]}'
    version: '1.0'
    sourceId: (empty(WorkspaceResourceGroup)
      ? Workspace.id
      : resourceId(WorkspaceResourceGroup, 'Microsoft.OperationalInsights/workspaces', WorkspaceName))
    category: 'sentinel'
  }
}

resource id_SOCRadar_EntraID_VIP_Workbook 'Microsoft.Insights/workbooks@2022-04-01' = {
  name: guid(resourceGroup().id, 'SOCRadar-EntraID-VIP-Workbook')
  location: resourceGroup().location
  kind: 'shared'
  properties: {
    displayName: 'SOCRadar Entra ID — VIP Protection'
    serializedData: '{"version": "Notebook/1.0", "items": [{"type": 1, "content": {"json": "## SOCRadar Entra ID \\u2014 VIP Protection Dashboard\\n> \\u26a0\\ufe0f **UNVERIFIED**: VIP Protection endpoint is not in official SOCRadar API documentation. Verified working in live tests but may change without notice.\\n\\nVIP user exposures found by SOCRadar, enriched with Microsoft Entra ID lookup."}, "name": "header"}, {"type": 9, "content": {"version": "KqlParameterItem/1.0", "parameters": [{"id": "tenant-id-param", "version": "KqlParameterItem/1.0", "name": "TenantId", "label": "Entra ID Tenant", "type": 2, "isRequired": true, "value": "All", "typeSettings": {"additionalResourceOptions": [], "includeAll": false, "showDefault": false}, "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "query": "union isfuzzy=true SOCRadar_VIP_CL\\n| where isnotempty(entra_tenant_id)\\n| distinct entra_tenant_id\\n| project value = entra_tenant_id, label = entra_tenant_id\\n| union (datatable(value:string, label:string)[\'All\',\'All\'])\\n| order by label asc"}]}, "name": "parameters - tenant"}, {"type": 1, "content": {"json": "---\\n### Overview"}, "name": "overview-header"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_VIP_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| count\\n| project Count", "size": 4, "title": "Total Records", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "tiles", "tileSettings": {"titleContent": {"columnMatch": "Count", "formatter": 12, "formatOptions": {"palette": "auto"}}, "showBorder": false}}, "customWidth": "33", "name": "total-records"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_VIP_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where entra_status == \\"found\\"\\n| count\\n| project Count", "size": 4, "title": "Found in Entra ID", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "tiles", "tileSettings": {"titleContent": {"columnMatch": "Count", "formatter": 12, "formatOptions": {"palette": "redBright"}}, "showBorder": false}}, "customWidth": "33", "name": "found-entra"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_VIP_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where TimeGenerated > ago(24h)\\n| count\\n| project Count", "size": 4, "title": "Last 24 Hours", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "tiles", "tileSettings": {"titleContent": {"columnMatch": "Count", "formatter": 12, "formatOptions": {"palette": "blue"}}, "showBorder": false}}, "customWidth": "33", "name": "last-24h"}, {"type": 1, "content": {"json": "---\\n### VIP Analysis"}, "name": "analysis-header"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_VIP_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| summarize Count=count() by entra_status\\n| order by Count desc", "size": 2, "title": "Entra ID Status", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "piechart"}, "customWidth": "50", "name": "entra-status-pie"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_VIP_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| summarize Count=count() by status\\n| order by Count desc", "size": 2, "title": "Record Status", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "barchart"}, "customWidth": "50", "name": "record-status"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_VIP_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| summarize Count=count() by keyword\\n| order by Count desc\\n| take 10", "size": 2, "title": "Top Keywords", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "barchart"}, "name": "top-keywords"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_VIP_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| summarize Count=count() by bin(TimeGenerated, 1d)\\n| order by TimeGenerated asc", "size": 0, "title": "Records Over Time", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "timechart"}, "name": "records-timeline"}, {"type": 1, "content": {"json": "---\\n### Recent Records"}, "name": "recent-header"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_VIP_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| project TimeGenerated, email, vip_name, keyword, status, discovery_date, entra_status\\n| order by TimeGenerated desc\\n| take 50", "size": 0, "title": "Recent VIP Records", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "table"}, "name": "recent-records"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_VIP_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where isnotempty(entra_tenant_id)\\n| extend src = case(Type == \'SOCRadar_Botnet_CL\', \'Botnet\', Type == \'SOCRadar_PII_CL\', \'PII\', Type == \'SOCRadar_VIP_CL\', \'VIP\', \'Other\')\\n| summarize Records=count(), Found=countif(entra_status == \'found\'), Compromised=countif(entra_status == \'compromised\') by entra_tenant_id, src\\n| order by Records desc", "size": 1, "title": "Tenant Breakdown", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "table"}, "name": "tenant-breakdown"}], "isLocked": false, "fallbackResourceIds": ["/subscriptions/{Subscription}/resourceGroups/{ResourceGroup}/providers/Microsoft.OperationalInsights/workspaces/{Workspace}"]}'
    version: '1.0'
    sourceId: (empty(WorkspaceResourceGroup)
      ? Workspace.id
      : resourceId(WorkspaceResourceGroup, 'Microsoft.OperationalInsights/workspaces', WorkspaceName))
    category: 'sentinel'
  }
}

resource id_SOCRadar_EntraID_Combined_Workbook 'Microsoft.Insights/workbooks@2022-04-01' = {
  name: guid(resourceGroup().id, 'SOCRadar-EntraID-Combined-Workbook')
  location: resourceGroup().location
  kind: 'shared'
  properties: {
    displayName: 'SOCRadar Entra ID — Combined'
    serializedData: '{"version": "Notebook/1.0", "items": [{"type": 1, "content": {"json": "## SOCRadar Entra ID \\u2014 Combined Dashboard\\nAll employee credential exposures across SOCRadar sources (Botnet Data, PII Exposure, VIP Protection), enriched with Microsoft Entra ID status and remediation actions."}, "name": "header"}, {"type": 9, "content": {"version": "KqlParameterItem/1.0", "parameters": [{"id": "tenant-id-param", "version": "KqlParameterItem/1.0", "name": "TenantId", "label": "Entra ID Tenant", "type": 2, "isRequired": true, "value": "All", "typeSettings": {"additionalResourceOptions": [], "includeAll": false, "showDefault": false}, "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "query": "union isfuzzy=true SOCRadar_Botnet_CL, SOCRadar_PII_CL, SOCRadar_VIP_CL\\n| where isnotempty(entra_tenant_id)\\n| distinct entra_tenant_id\\n| project value = entra_tenant_id, label = entra_tenant_id\\n| union (datatable(value:string, label:string)[\'All\',\'All\'])\\n| order by label asc"}]}, "name": "parameters - tenant"}, {"type": 1, "content": {"json": "---\\n### Overall Overview"}, "name": "overview-header"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "union isfuzzy=true SOCRadar_Botnet_CL, SOCRadar_PII_CL, SOCRadar_VIP_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| count\\n| project Count", "size": 4, "title": "Total Records (All Sources)", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "tiles", "tileSettings": {"titleContent": {"columnMatch": "Count", "formatter": 12, "formatOptions": {"palette": "auto"}}, "showBorder": false}}, "customWidth": "25", "name": "total-all"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "union isfuzzy=true SOCRadar_Botnet_CL, SOCRadar_PII_CL, SOCRadar_VIP_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where entra_status == \\"found\\"\\n| count\\n| project Count", "size": 4, "title": "Employees Found in Entra ID", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "tiles", "tileSettings": {"titleContent": {"columnMatch": "Count", "formatter": 12, "formatOptions": {"palette": "redBright"}}, "showBorder": false}}, "customWidth": "25", "name": "found-all"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "union isfuzzy=true SOCRadar_Botnet_CL, SOCRadar_PII_CL, SOCRadar_VIP_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where entra_status == \\"compromised\\"\\n| count\\n| project Count", "size": 4, "title": "Confirmed Compromised", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "tiles", "tileSettings": {"titleContent": {"columnMatch": "Count", "formatter": 12, "formatOptions": {"palette": "red"}}, "showBorder": false}}, "customWidth": "25", "name": "compromised-all"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_EntraID_Audit_CL\\n| where TimeGenerated > ago(24h)\\n| summarize Actions=sum(toint(actions_taken))\\n| project Actions", "size": 4, "title": "Actions Taken (24h)", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "tiles", "tileSettings": {"titleContent": {"columnMatch": "Actions", "formatter": 12, "formatOptions": {"palette": "green"}}, "showBorder": false}}, "customWidth": "25", "name": "actions-24h"}, {"type": 1, "content": {"json": "---\\n### Records by Source"}, "name": "by-source-header"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "union isfuzzy=true\\n(SOCRadar_Botnet_CL | extend Source=\\"Botnet\\"),\\n(SOCRadar_PII_CL | extend Source=\\"PII\\"),\\n(SOCRadar_VIP_CL | extend Source=\\"VIP\\")\\n| summarize Count=count() by Source\\n| order by Count desc", "size": 2, "title": "Records by Source", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "piechart"}, "customWidth": "50", "name": "records-by-source"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "union isfuzzy=true\\n(SOCRadar_Botnet_CL | extend Source=\\"Botnet\\"),\\n(SOCRadar_PII_CL | extend Source=\\"PII\\"),\\n(SOCRadar_VIP_CL | extend Source=\\"VIP\\")\\n| summarize Count=count() by entra_status, Source\\n| order by Count desc", "size": 2, "title": "Entra ID Status by Source", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "barchart"}, "customWidth": "50", "name": "status-by-source"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "union isfuzzy=true\\n(SOCRadar_Botnet_CL | extend Source=\\"Botnet\\"),\\n(SOCRadar_PII_CL | extend Source=\\"PII\\"),\\n(SOCRadar_VIP_CL | extend Source=\\"VIP\\")\\n| summarize Count=count() by bin(TimeGenerated, 1d), Source\\n| order by TimeGenerated asc", "size": 0, "title": "Records Over Time by Source", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "timechart"}, "name": "timeline-by-source"}, {"type": 1, "content": {"json": "---\\n### Audit Log"}, "name": "audit-header"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_EntraID_Audit_CL\\n| summarize Count=count() by source\\n| order by Count desc", "size": 2, "title": "Import Runs by Source", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "barchart"}, "customWidth": "50", "name": "audit-by-source"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_EntraID_Audit_CL\\n| summarize Found=sum(toint(found_count)), NotFound=sum(toint(not_found_count)), Actions=sum(toint(actions_taken)), Errors=sum(toint(error_count)) by bin(TimeGenerated, 1h)\\n| order by TimeGenerated asc", "size": 0, "title": "Audit Metrics Over Time", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "timechart"}, "customWidth": "50", "name": "audit-metrics-timeline"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "SOCRadar_EntraID_Audit_CL\\n| project TimeGenerated, source, total_records, employee_records, found_count, not_found_count, actions_taken, error_count, duration_sec\\n| order by TimeGenerated desc\\n| take 30", "size": 0, "title": "Recent Import Runs", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "table"}, "name": "recent-runs"}, {"type": 1, "content": {"json": "---\\n### High-Risk Accounts"}, "name": "highrisk-header"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "union isfuzzy=true\\n(SOCRadar_Botnet_CL | extend Source=\\"Botnet\\"),\\n(SOCRadar_PII_CL | extend Source=\\"PII\\")\\n| where entra_status in (\\"found\\", \\"compromised\\")\\n| where password_present == true\\n| project TimeGenerated, Source, email, entra_status, is_plaintext, actions_taken\\n| order by TimeGenerated desc\\n| take 50", "size": 0, "title": "Employees Found in Entra ID with Password", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "table"}, "name": "high-risk-accounts"}, {"type": 3, "content": {"version": "KqlItem/1.0", "query": "union isfuzzy=true SOCRadar_Botnet_CL, SOCRadar_PII_CL, SOCRadar_VIP_CL\\n| where \'{TenantId}\' == \'All\' or entra_tenant_id == \'{TenantId}\'\\n| where isnotempty(entra_tenant_id)\\n| extend src = case(Type == \'SOCRadar_Botnet_CL\', \'Botnet\', Type == \'SOCRadar_PII_CL\', \'PII\', Type == \'SOCRadar_VIP_CL\', \'VIP\', \'Other\')\\n| summarize Records=count(), Found=countif(entra_status == \'found\'), Compromised=countif(entra_status == \'compromised\') by entra_tenant_id, src\\n| order by Records desc", "size": 1, "title": "Tenant Breakdown", "queryType": 0, "resourceType": "microsoft.operationalinsights/workspaces", "visualization": "table"}, "name": "tenant-breakdown"}], "isLocked": false, "fallbackResourceIds": ["/subscriptions/{Subscription}/resourceGroups/{ResourceGroup}/providers/Microsoft.OperationalInsights/workspaces/{Workspace}"]}'
    version: '1.0'
    sourceId: (empty(WorkspaceResourceGroup)
      ? Workspace.id
      : resourceId(WorkspaceResourceGroup, 'Microsoft.OperationalInsights/workspaces', WorkspaceName))
    category: 'sentinel'
  }
}

output functionAppName string = functionAppName
output storageAccountName string = storageAccountName
output pollingSchedule string = pollingSchedule
output managedIdentityPrincipalId string = reference(managedIdentity.id, '2023-01-31', 'Full').properties.principalId
output entraIdClientId string = resolvedAppClientId
output ficCommandToRun string = CreateAppRegistration ? 'No manual FIC step needed — App Registration and Federated Identity Credential created automatically by ARM.' : 'az ad app federated-credential create --id ${EntraIdClientId} --parameters \'{"name":"socradar-entraid-uami","issuer":"https://login.microsoftonline.com/${(empty(EntraIdTenantId)?subscription().tenantId:EntraIdTenantId)}/v2.0","subject":"${reference(managedIdentity.id,'2023-01-31','Full').properties.principalId}","audiences":["api://AzureADTokenExchange"]}\''
output nextStep string = (!CreateAppRegistration) ? 'Copy ficCommandToRun and run it in Azure CLI to enable Federated Identity Credential. Then Function App starts working on next timer cycle.' : (GrantAdminConsent ? 'Zero-touch deployment complete. App Registration, Federated Identity Credential, and Graph admin consent all granted by ARM. Function App starts on next timer cycle.' : 'Final manual step (1 portal click): Portal → Microsoft Entra ID → App registrations → SOCRadar Entra ID Integration → API permissions → Grant admin consent. Then Function App starts on next timer cycle. (To skip this step on next deployment, set GrantAdminConsent=true and ensure deployer has Cloud Application Administrator role.)')
