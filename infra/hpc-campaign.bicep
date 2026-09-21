targetScope = 'resourceGroup'

metadata description = 'Disposable Slurm plus Azure Managed Lustre campaign resources for task 5.3/5.4 validation.'

@description('Region hosting the campaign resources.')
param location string

@description('Tags copied from the parent disposable environment.')
param tags object

@description('Existing VNet name that hosts compute and private endpoints.')
param virtualNetworkName string

@description('Name of the compute subnet used by the Slurm scheduler VM.')
param computeSubnetName string = 'snet-compute'

@description('Dedicated AMLFS subnet prefix. Azure Managed Lustre requires its own subnet.')
param lustreSubnetPrefix string = '10.42.2.0/24'

@description('Temporary storage account used for HSM import/export.')
param storageAccountName string = 'stghpc${uniqueString(resourceGroup().id)}'

@description('Object id of the HPC Cache Resource Provider service principal.')
param amlfsProviderObjectId string = ''

@description('Existing user-assigned identity resource IDs attached to the Slurm VM.')
param userAssignedIdentityIds array

@description('Principal id that uploads the synthetic seed bundle into the temporary HSM storage account.')
param batchIdentityPrincipalId string = ''

@description('SSH public key required by Azure Linux provisioning. Run-command remains the primary access path.')
param adminPublicKey string

param slurmVmName string = 'vm-slurm-hpc-20260921'
param dataContainerName string = 'amlfs-hsm'
param loggingContainerName string = 'amlfs-logs'
param amlfsName string = 'amlfs-genomics-20260921'
param amlfsSkuName string = 'AMLFS-Durable-Premium-500'
param amlfsCapacityTiB int = 4
param slurmVmSize string = 'Standard_D4s_v7'
param slurmAvailabilityZone string = '1'
param amlfsAvailabilityZone string = '1'
param enableHsm bool = true

var blobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageAccountContributorRoleId = '17d1049b-9a84-46fb-8f53-869881c3d3ab'

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: virtualNetworkName
}

resource computeSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: computeSubnetName
}

resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' existing = {
  parent: storage
  name: 'default'
}

resource lustreSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: 'snet-managed-lustre'
  properties: {
    addressPrefix: lustreSubnetPrefix
    privateEndpointNetworkPolicies: 'Disabled'
    privateLinkServiceNetworkPolicies: 'Enabled'
  }
}

resource dataContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: blobService
  name: dataContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource loggingContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: blobService
  name: loggingContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource amlfsStorageContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(amlfsProviderObjectId)) {
  scope: storage
  name: guid(storage.id, amlfsProviderObjectId, storageAccountContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageAccountContributorRoleId)
    principalId: amlfsProviderObjectId
    principalType: 'ServicePrincipal'
  }
}

resource amlfsBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(amlfsProviderObjectId)) {
  scope: storage
  name: guid(storage.id, amlfsProviderObjectId, blobDataContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
    principalId: amlfsProviderObjectId
    principalType: 'ServicePrincipal'
  }
}

resource batchBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(batchIdentityPrincipalId)) {
  scope: storage
  name: guid(storage.id, batchIdentityPrincipalId, blobDataContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
    principalId: batchIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

module slurmScheduler 'modules/slurm-scheduler.bicep' = {
  name: 'slurm-scheduler'
  params: {
    location: location
    tags: tags
    name: slurmVmName
    subnetId: computeSubnet.id
    adminPublicKey: adminPublicKey
    vmSize: slurmVmSize
    userAssignedIdentityIds: userAssignedIdentityIds
    zone: slurmAvailabilityZone
  }
}

module managedLustre 'modules/managed-lustre.bicep' = {
  name: 'managed-lustre'
  params: {
    location: location
    tags: tags
    name: amlfsName
    subnetId: lustreSubnet.id
    dataContainerId: enableHsm ? dataContainer.id : ''
    loggingContainerId: enableHsm ? loggingContainer.id : ''
    skuName: amlfsSkuName
    storageCapacityTiB: amlfsCapacityTiB
    zone: amlfsAvailabilityZone
  }
}

output slurmVmName string = slurmScheduler.outputs.vmName
output slurmVmPrivateIp string = slurmScheduler.outputs.privateIpAddress
output amlfsId string = managedLustre.outputs.filesystemId
output amlfsName string = managedLustre.outputs.filesystemName
output storageAccountName string = storage.name
output dataContainerId string = dataContainer.id
output loggingContainerId string = loggingContainer.id
output lustreSubnetId string = lustreSubnet.id
