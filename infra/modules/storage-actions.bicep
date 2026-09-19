metadata description = 'Storage Actions lifecycle task for staged genomic artifacts (task 3.5). Tiers cold staged artifacts without moving or renaming them, so source_file_uri and lineage links keep resolving.'

param location string
param tags object
param name string

@description('Name of the lake storage account holding staged artifacts.')
param lakeAccountName string

@description('Filesystem (container) holding the healthcare data solutions taxonomy.')
param lakeFilesystem string

@description('ISO 8601 UTC instant; a Hot staged artifact whose Last-Modified time is before this instant is tiered to Cool. Computed by the caller from the age threshold so the deployment stays free of utcNow(), which would make every re-run report a change and break idempotency (task 11.4).')
param tierBeforeDateUtc string

@description('When the one-shot verification run executes, in ISO 8601 UTC. Must be in the future at deployment time.')
param verificationRunStartUtc string

@description('Deploy the one-shot verification assignment that actually executes the task. Defaults to false: Azure Storage Actions can only reach a storage account through its public data-plane endpoint (a resourceAccessRules network rule, verified against the live account, is rejected for Microsoft.StorageActions/storageTasks even though it is documented as a supported trusted-access resource type), so an assignment cannot run while task 8.7 keeps publicNetworkAccess Disabled. The task definition above still deploys and validates independently of this switch.')
param deployAssignment bool = false

// HNS/ADLS Gen2 accounts (the lake account) do not support blob index tags: the Storage Actions
// condition/operation reference documents Tags.Value[] and SetBlobTags as unavailable wherever a
// hierarchical namespace is enabled. Task 3.5 asks for "tiering and index tags"; only tiering is
// achievable on this account without weakening it to a flat namespace, which task 7.9's OneLake
// shortcuts and the folder taxonomy require. This is an explicit platform constraint, not a
// silently dropped requirement or a faked substitute tagging mechanism.
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource lakeAccount 'Microsoft.Storage/storageAccounts@2025-01-01' existing = {
  name: lakeAccountName
}

resource task 'Microsoft.StorageActions/storageTasks@2023-01-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    enabled: true
    description: 'Tiers Ingest/ artifacts Hot to Cool past threshold. No index tags: unsupported on HNS accounts.'
    action: {
      if: {
        condition: '[[and(startsWith(Name, \'Ingest/\'), equals(AccessTier, \'Hot\'), less(Last-Modified, \'${tierBeforeDateUtc}\'))]]'
        operations: [
          {
            name: 'SetBlobTier'
            onSuccess: 'continue'
            onFailure: 'break'
            parameters: {
              tier: 'Cool'
            }
          }
        ]
      }
    }
  }
}

resource taskExecutionRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: lakeAccount
  name: guid(lakeAccount.id, task.id, storageBlobDataContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: task.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// A one-shot verification run: the demo does not keep a recurring schedule billing task-execution
// charges while the foundation sits idle for dependent HPC/end-to-end work.
resource assignment 'Microsoft.Storage/storageAccounts/storageTaskAssignments@2024-01-01' = if (deployAssignment) {
  parent: lakeAccount
  name: '${name}run1'
  properties: {
    taskId: task.id
    enabled: true
    description: 'One-shot verification pass over staged Ingest/ artifacts.'
    executionContext: {
      target: {
        prefix: [
          '${lakeFilesystem}/Ingest/'
        ]
      }
      trigger: {
        type: 'RunOnce'
        parameters: {
          startOn: verificationRunStartUtc
        }
      }
    }
    report: {
      prefix: '${lakeFilesystem}/StorageTaskReports/${name}'
    }
  }
  dependsOn: [
    taskExecutionRole
  ]
}

output taskId string = task.id
output taskName string = task.name
output assignmentName string = deployAssignment ? assignment!.name : ''
output taskPrincipalId string = task.identity.principalId
