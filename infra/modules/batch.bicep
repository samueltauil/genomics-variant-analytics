metadata description = 'Managed-identity Azure Batch target with private HNS work storage.'

param location string
param tags object

@minLength(3)
@maxLength(24)
param accountName string

@minLength(3)
@maxLength(24)
param storageAccountName string

param poolName string = 'secondary-analysis-pool'
param poolVmSize string = 'Standard_D2s_v5'
param subnetId string
param batchIdentityResourceId string
param batchIdentityPrincipalId string
param deployerPrincipalId string
param containerRegistryLoginServer string = ''

var blobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var batchAccountContributorRoleId = '29fe4964-1e60-436b-bd3a-77fd4c178b3c'

resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    isHnsEnabled: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: storage
  name: 'default'
}

resource workContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: blobService
  name: 'batch-work'
  properties: {
    publicAccess: 'None'
  }
}

resource batchStorageAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, batchIdentityPrincipalId, blobDataContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
    principalId: batchIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource account 'Microsoft.Batch/batchAccounts@2024-07-01' = {
  name: accountName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${batchIdentityResourceId}': {}
    }
  }
  properties: {
    allowedAuthenticationModes: [
      'AAD'
      'TaskAuthenticationToken'
    ]
    autoStorage: {
      authenticationMode: 'BatchAccountManagedIdentity'
      nodeIdentityReference: {
        resourceId: batchIdentityResourceId
      }
      storageAccountId: storage.id
    }
    encryption: {
      keySource: 'Microsoft.Batch'
    }
    poolAllocationMode: 'BatchService'
    publicNetworkAccess: 'Enabled'
  }
}

resource pool 'Microsoft.Batch/batchAccounts/pools@2024-07-01' = {
  parent: account
  name: poolName
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${batchIdentityResourceId}': {}
    }
  }
  properties: {
    deploymentConfiguration: {
      virtualMachineConfiguration: {
        imageReference: {
          publisher: 'microsoft-dsvm'
          offer: 'ubuntu-hpc'
          sku: '2404'
          version: 'latest'
        }
        nodeAgentSkuId: 'batch.node.ubuntu 24.04'
        containerConfiguration: {
          type: 'DockerCompatible'
          containerRegistries: empty(containerRegistryLoginServer) ? [] : [
            {
              registryServer: containerRegistryLoginServer
              identityReference: {
                resourceId: batchIdentityResourceId
              }
            }
          ]
        }
      }
    }
    networkConfiguration: {
      publicIPAddressConfiguration: {
        provision: 'NoPublicIPAddresses'
      }
      subnetId: subnetId
    }
    scaleSettings: {
      autoScale: {
        evaluationInterval: 'PT5M'
        formula: '''
          $samples = $PendingTasks.GetSamplePercent(TimeInterval_Minute * 5);
          $tasks = $samples < 70 ? max(0, $PendingTasks.GetSample(1)) : max($PendingTasks.GetSample(1), avg($PendingTasks.GetSample(TimeInterval_Minute * 5)));
          $TargetDedicatedNodes = max(0, min(2, $tasks));
          $NodeDeallocationOption = taskcompletion;
        '''
      }
    }
    targetNodeCommunicationMode: 'Simplified'
    taskSchedulingPolicy: {
      nodeFillType: 'Pack'
    }
    taskSlotsPerNode: 2
    vmSize: poolVmSize
  }
}

resource batchOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, deployerPrincipalId, batchAccountContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', batchAccountContributorRoleId)
    principalId: deployerPrincipalId
  }
}

output accountName string = account.name
output accountEndpoint string = account.properties.accountEndpoint
output poolName string = pool.name
output storageAccountName string = storage.name
output storageAccountId string = storage.id
output workContainerName string = workContainer.name
