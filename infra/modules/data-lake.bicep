metadata description = 'ADLS Gen2 landing account for staged genomic artifacts (tasks 1.4, 8.1).'

param location string
param tags object

@minLength(3)
@maxLength(24)
param storageAccountName string

@description('Container holding the healthcare data solutions folder taxonomy. Container names cannot preserve case, so the taxonomy lives in directories beneath it.')
param filesystemName string = 'healthcare'

param stagingPrincipalId string
param pipelinePrincipalId string
param deployerPrincipalId string

@description('Private endpoints replace this in task 8.7; until then the account is reachable for acceptance testing.')
param allowPublicNetworkAccess bool = true

var blobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var blobDataReaderRoleId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
var blobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'

resource account 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    isHnsEnabled: true
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    publicNetworkAccess: allowPublicNetworkAccess ? 'Enabled' : 'Disabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: allowPublicNetworkAccess ? 'Allow' : 'Deny'
    }
  }
}

resource blobServices 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: account
  name: 'default'
  properties: {
    // Blob versioning is unavailable on hierarchical-namespace accounts; reference immutability
    // in task 4.2 therefore cannot rely on it.
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource filesystem 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: blobServices
  name: filesystemName
  properties: {
    publicAccess: 'None'
  }
}

resource stagingWrite 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, stagingPrincipalId, blobDataContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
    principalId: stagingPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// The pipeline identity reads staged artifacts; task 1.4 asserts it cannot write them.
resource pipelineRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, pipelinePrincipalId, blobDataReaderRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataReaderRoleId)
    principalId: pipelinePrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerVerify 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, deployerPrincipalId, blobDataOwnerRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataOwnerRoleId)
    principalId: deployerPrincipalId
  }
}

output storageAccountName string = account.name
output storageAccountId string = account.id
output filesystemName string = filesystem.name
output dfsEndpoint string = account.properties.primaryEndpoints.dfs
