// Alert-backed incidents (IncidentMode = AlertBacked): one scheduled analytics
// rule per source, so every incident has an alert behind it and shows in the
// Microsoft Defender portal. An incident created through the Sentinel incidents
// API has no alert and is not synchronized to Defender.
//
// Deployed in every mode and switched by `Enabled`: a redeploy with another
// mode turns the rules off instead of leaving them next to the direct path.
//
// The queries select named columns only. The credential columns of the three
// tables are never read, so nothing secret can reach an alert.

@description('Microsoft Sentinel Log Analytics Workspace Name')
param WorkspaceName string

@description('true when IncidentMode is AlertBacked')
param Enabled bool

var botnetRuleId = guid(WorkspaceName, 'socradar-entraid-botnet-rule')
var piiRuleId = guid(WorkspaceName, 'socradar-entraid-pii-rule')
var vipRuleId = guid(WorkspaceName, 'socradar-entraid-vip-rule')
var labelerId = guid(WorkspaceName, 'socradar-entraid-labeler')

var accountMapping = {
  entityType: 'Account'
  fieldMappings: [
    { identifier: 'Name', columnName: 'AccountName' }
    { identifier: 'UPNSuffix', columnName: 'UPNSuffix' }
  ]
}

var customDetails = {
  AlarmId: 'AlarmIdText'
  Source: 'SourceName'
  EntraStatus: 'EntraStatus'
  ActionsTaken: 'ActionsTaken'
  SocradarSeverity: 'SocradarSeverity'
  DedupKey: 'DedupKey'
}

var alertDetails = {
  alertDisplayNameFormat: 'SOCRadar: Leaked credential detected ({{SourceName}})'
  alertDescriptionFormat: 'SOCRadar detected a leaked credential for {{AccountDisplay}}. Source: {{SourceName}}. Recommended actions: revoke sessions, force a credential reset, review sign-in activity.'
  alertSeverityColumnName: 'SentinelSeverity'
}

var incidentConfiguration = {
  createIncident: true
  groupingConfiguration: {
    enabled: false
    reopenClosedIncident: false
    lookbackDuration: 'PT5H'
    matchingMethod: 'AllEntities'
    groupByEntities: []
    groupByAlertDetails: []
    groupByCustomDetails: []
  }
}

resource botnetRule 'Microsoft.OperationalInsights/workspaces/providers/alertRules@2024-03-01' = {
  name: '${WorkspaceName}/Microsoft.SecurityInsights/${botnetRuleId}'
  kind: 'Scheduled'
  properties: {
    displayName: 'SOCRadar Entra ID - Leaked credential (Botnet)'
    description: 'Raises one alert, and one incident, for every leaked employee credential in SOCRadar_Botnet_CL. The Function App needs no Microsoft Sentinel role for this: the rule only reads the table.'
    severity: 'Medium'
    enabled: Enabled
    queryFrequency: 'PT1H'
    queryPeriod: 'P7D'
    triggerOperator: 'GreaterThan'
    triggerThreshold: 0
    suppressionDuration: 'PT5H'
    suppressionEnabled: false
    tactics: [ 'InitialAccess' ]
    techniques: [ 'T1078' ]
    eventGroupingSettings: { aggregationKind: 'AlertPerResult' }
    alertDetailsOverride: alertDetails
    customDetails: customDetails
    entityMappings: [
      accountMapping
      {
        entityType: 'IP'
        fieldMappings: [
          { identifier: 'Address', columnName: 'DeviceIp' }
        ]
      }
    ]
    incidentConfiguration: incidentConfiguration
    query: '''
// One alert per leaked account and alarm. The platform runs a rule about 6 minutes behind the clock,
// so a row is held back until it is 12 minutes old, which lets the previous run's alerts show up here
// first. Keys that already have an alert are dropped, so a late run cannot alert twice and an incident
// closed by an analyst is not followed by a second one. The look-back is the rule's queryPeriod (7 days):
// the rule engine does not read SecurityAlert further back than that (measured). A period of two days or
// more needs a run frequency of at least one hour. Custom Details is a second, still-encoded JSON
// string with 1-element arrays. isfuzzy keeps the rule alive where SecurityAlert does not exist yet.
let Alerted = union isfuzzy=true (datatable(ExtendedProperties:string)[]), SecurityAlert
| extend AlertedKey = tostring(parse_json(tostring(parse_json(tostring(ExtendedProperties))['Custom Details'])).DedupKey[0])
| where isnotempty(AlertedKey)
| distinct AlertedKey;
SOCRadar_Botnet_CL
| where ingestion_time() > ago(7d)
| where ingestion_time() < ago(12m)
| where isnotempty(email)
| project TimeGenerated, email, source, alarm_id, severity, entra_status, actions_taken, device_ip
| extend DedupKey = strcat(source, "|", tostring(alarm_id), "|", tolower(email))
| join kind=leftanti Alerted on $left.DedupKey == $right.AlertedKey
| summarize arg_max(TimeGenerated, *) by DedupKey
| extend AccountName = tostring(split(email, "@")[0]), UPNSuffix = tostring(split(email, "@")[1])
| extend AccountDisplay = iff(isnotempty(UPNSuffix), strcat(AccountName, "@", UPNSuffix), AccountName)
| extend SourceName = toupper(source), AlarmIdText = tostring(alarm_id), EntraStatus = coalesce(entra_status, "unknown")
| extend ActionsTaken = tostring(actions_taken), SocradarSeverity = toupper(severity)
| extend SentinelSeverity = case(SocradarSeverity in ("CRITICAL", "HIGH"), "High", SocradarSeverity == "LOW", "Low", "Medium")
| extend DeviceIp = iff(device_ip matches regex @"^\d{1,3}(\.\d{1,3}){3}$", device_ip, "")
| project TimeGenerated, DedupKey, AccountName, UPNSuffix, AccountDisplay, SourceName, AlarmIdText, EntraStatus, ActionsTaken, SocradarSeverity, SentinelSeverity, DeviceIp
| order by TimeGenerated asc
| take 149
'''
  }
}

resource piiRule 'Microsoft.OperationalInsights/workspaces/providers/alertRules@2024-03-01' = {
  name: '${WorkspaceName}/Microsoft.SecurityInsights/${piiRuleId}'
  kind: 'Scheduled'
  properties: {
    displayName: 'SOCRadar Entra ID - Leaked credential (PII exposure)'
    description: 'Raises one alert, and one incident, for every leaked employee credential in SOCRadar_PII_CL. The Function App needs no Microsoft Sentinel role for this: the rule only reads the table.'
    severity: 'Medium'
    enabled: Enabled
    queryFrequency: 'PT1H'
    queryPeriod: 'P7D'
    triggerOperator: 'GreaterThan'
    triggerThreshold: 0
    suppressionDuration: 'PT5H'
    suppressionEnabled: false
    tactics: [ 'InitialAccess' ]
    techniques: [ 'T1078' ]
    eventGroupingSettings: { aggregationKind: 'AlertPerResult' }
    alertDetailsOverride: alertDetails
    customDetails: customDetails
    entityMappings: [
      accountMapping
    ]
    incidentConfiguration: incidentConfiguration
    query: '''
// One alert per leaked account and alarm. The platform runs a rule about 6 minutes behind the clock,
// so a row is held back until it is 12 minutes old, which lets the previous run's alerts show up here
// first. Keys that already have an alert are dropped, so a late run cannot alert twice and an incident
// closed by an analyst is not followed by a second one. The look-back is the rule's queryPeriod (7 days):
// the rule engine does not read SecurityAlert further back than that (measured). A period of two days or
// more needs a run frequency of at least one hour. Custom Details is a second, still-encoded JSON
// string with 1-element arrays. isfuzzy keeps the rule alive where SecurityAlert does not exist yet.
let Alerted = union isfuzzy=true (datatable(ExtendedProperties:string)[]), SecurityAlert
| extend AlertedKey = tostring(parse_json(tostring(parse_json(tostring(ExtendedProperties))['Custom Details'])).DedupKey[0])
| where isnotempty(AlertedKey)
| distinct AlertedKey;
SOCRadar_PII_CL
| where ingestion_time() > ago(7d)
| where ingestion_time() < ago(12m)
| where isnotempty(email)
| project TimeGenerated, email, source, alarm_id, severity, entra_status, actions_taken
| extend DedupKey = strcat(source, "|", tostring(alarm_id), "|", tolower(email))
| join kind=leftanti Alerted on $left.DedupKey == $right.AlertedKey
| summarize arg_max(TimeGenerated, *) by DedupKey
| extend AccountName = tostring(split(email, "@")[0]), UPNSuffix = tostring(split(email, "@")[1])
| extend AccountDisplay = iff(isnotempty(UPNSuffix), strcat(AccountName, "@", UPNSuffix), AccountName)
| extend SourceName = toupper(source), AlarmIdText = tostring(alarm_id), EntraStatus = coalesce(entra_status, "unknown")
| extend ActionsTaken = tostring(actions_taken), SocradarSeverity = toupper(severity)
| extend SentinelSeverity = case(SocradarSeverity in ("CRITICAL", "HIGH"), "High", SocradarSeverity == "LOW", "Low", "Medium")
| project TimeGenerated, DedupKey, AccountName, UPNSuffix, AccountDisplay, SourceName, AlarmIdText, EntraStatus, ActionsTaken, SocradarSeverity, SentinelSeverity
| order by TimeGenerated asc
| take 149
'''
  }
}

resource vipRule 'Microsoft.OperationalInsights/workspaces/providers/alertRules@2024-03-01' = {
  name: '${WorkspaceName}/Microsoft.SecurityInsights/${vipRuleId}'
  kind: 'Scheduled'
  properties: {
    displayName: 'SOCRadar Entra ID - Leaked credential (VIP protection)'
    description: 'Raises one alert, and one incident, for every leaked employee credential in SOCRadar_VIP_CL. The Function App needs no Microsoft Sentinel role for this: the rule only reads the table.'
    severity: 'Medium'
    enabled: Enabled
    queryFrequency: 'PT1H'
    queryPeriod: 'P7D'
    triggerOperator: 'GreaterThan'
    triggerThreshold: 0
    suppressionDuration: 'PT5H'
    suppressionEnabled: false
    tactics: [ 'InitialAccess' ]
    techniques: [ 'T1078' ]
    eventGroupingSettings: { aggregationKind: 'AlertPerResult' }
    alertDetailsOverride: alertDetails
    customDetails: customDetails
    entityMappings: [
      accountMapping
    ]
    incidentConfiguration: incidentConfiguration
    query: '''
// One alert per leaked account and alarm. The platform runs a rule about 6 minutes behind the clock,
// so a row is held back until it is 12 minutes old, which lets the previous run's alerts show up here
// first. Keys that already have an alert are dropped, so a late run cannot alert twice and an incident
// closed by an analyst is not followed by a second one. The look-back is the rule's queryPeriod (7 days):
// the rule engine does not read SecurityAlert further back than that (measured). A period of two days or
// more needs a run frequency of at least one hour. Custom Details is a second, still-encoded JSON
// string with 1-element arrays. isfuzzy keeps the rule alive where SecurityAlert does not exist yet.
let Alerted = union isfuzzy=true (datatable(ExtendedProperties:string)[]), SecurityAlert
| extend AlertedKey = tostring(parse_json(tostring(parse_json(tostring(ExtendedProperties))['Custom Details'])).DedupKey[0])
| where isnotempty(AlertedKey)
| distinct AlertedKey;
SOCRadar_VIP_CL
| where ingestion_time() > ago(7d)
| where ingestion_time() < ago(12m)
| where isnotempty(email)
| project TimeGenerated, email, source, alarm_id, severity, entra_status, actions_taken
| extend DedupKey = strcat(source, "|", tostring(alarm_id), "|", tolower(email))
| join kind=leftanti Alerted on $left.DedupKey == $right.AlertedKey
| summarize arg_max(TimeGenerated, *) by DedupKey
| extend AccountName = tostring(split(email, "@")[0]), UPNSuffix = tostring(split(email, "@")[1])
| extend AccountDisplay = iff(isnotempty(UPNSuffix), strcat(AccountName, "@", UPNSuffix), AccountName)
| extend SourceName = toupper(source), AlarmIdText = tostring(alarm_id), EntraStatus = coalesce(entra_status, "unknown")
| extend ActionsTaken = tostring(actions_taken), SocradarSeverity = toupper(severity)
| extend SentinelSeverity = case(SocradarSeverity in ("CRITICAL", "HIGH"), "High", SocradarSeverity == "LOW", "Low", "Medium")
| project TimeGenerated, DedupKey, AccountName, UPNSuffix, AccountDisplay, SourceName, AlarmIdText, EntraStatus, ActionsTaken, SocradarSeverity, SentinelSeverity
| order by TimeGenerated asc
| take 149
'''
  }
}

// Same tags the direct path puts on its incidents.
resource labeler 'Microsoft.OperationalInsights/workspaces/providers/automationRules@2024-03-01' = {
  name: '${WorkspaceName}/Microsoft.SecurityInsights/${labelerId}'
  dependsOn: [
    botnetRule
    piiRule
    vipRule
  ]
  properties: {
    displayName: 'SOCRadar Entra ID - label incidents created by the alert-backed rules'
    order: 1
    triggeringLogic: {
      isEnabled: Enabled
      triggersOn: 'Incidents'
      triggersWhen: 'Created'
      conditions: [
        {
          conditionType: 'Property'
          conditionProperties: {
            propertyName: 'IncidentRelatedAnalyticRuleIds'
            operator: 'Contains'
            propertyValues: [
              resourceId('Microsoft.OperationalInsights/workspaces/providers/alertRules', WorkspaceName, 'Microsoft.SecurityInsights', botnetRuleId)
              resourceId('Microsoft.OperationalInsights/workspaces/providers/alertRules', WorkspaceName, 'Microsoft.SecurityInsights', piiRuleId)
              resourceId('Microsoft.OperationalInsights/workspaces/providers/alertRules', WorkspaceName, 'Microsoft.SecurityInsights', vipRuleId)
            ]
          }
        }
      ]
    }
    actions: [
      {
        order: 1
        actionType: 'ModifyProperties'
        actionConfiguration: {
          labels: [
            { labelName: 'SOCRadar' }
            { labelName: 'LeakedCredential' }
          ]
        }
      }
    ]
  }
}
