// The four custom tables this integration writes into, deployed into whichever
// resource group holds the workspace.
//
// They used to sit in the root template as `parent: Workspace`. That works only
// when this deployment is the one creating the workspace: with
// WorkspaceResourceGroup set, `Workspace` is not deployed, the table names
// resolved in the deployment's own resource group, and a cross-resource-group
// install failed with four ParentResourceNotFound errors after creating 11 other
// resources (measured 7 Sep 2026, task_azure_0062).
//
// The caller passes the scope, so the same declarations serve both cases.

@description('Log Analytics workspace that receives these tables. Must already exist or be created by the caller.')
param WorkspaceName string

resource ws 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: WorkspaceName
}

resource SOCRadar_Botnet_CL 'Microsoft.OperationalInsights/workspaces/tables@2022-10-01' = {
  parent: ws
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

resource SOCRadar_PII_CL 'Microsoft.OperationalInsights/workspaces/tables@2022-10-01' = {
  parent: ws
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

resource SOCRadar_VIP_CL 'Microsoft.OperationalInsights/workspaces/tables@2022-10-01' = {
  parent: ws
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

resource SOCRadar_EntraID_Audit_CL 'Microsoft.OperationalInsights/workspaces/tables@2022-10-01' = {
  parent: ws
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
          name: 'domain_filtered'
          type: 'int'
        }
        {
          name: 'no_address_count'
          type: 'int'
        }
        {
          name: 'lookup_disabled_count'
          type: 'int'
        }
        {
          name: 'no_token_count'
          type: 'int'
        }
        {
          name: 'lookup_failed_count'
          type: 'int'
        }
        {
          name: 'truncated'
          type: 'boolean'
        }
        {
          name: 'capped'
          type: 'boolean'
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
