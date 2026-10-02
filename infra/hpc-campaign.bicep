targetScope = 'resourceGroup'

metadata description = 'Campaign-owned Slurm and ephemeral Azure Managed Lustre resources using private managed-identity Blob staging.'

@description('Region hosting the campaign resources.')
param location string

@description('Stable identifier for this single campaign.')
@minLength(3)
@maxLength(32)
param campaignId string

@description('Opaque owner value required by guarded teardown.')
@minLength(3)
param campaignOwner string

@description('Date this disposable campaign is expected to be deleted, as YYYY-MM-DD.')
param expiresOn string

@description('SSH public key required by Azure Linux provisioning. Run-command remains the primary access path.')
param adminPublicKey string

@description('Existing private image or Compute Gallery image version containing the validated host-tool runtime and repository checkout.')
@minLength(1)
param slurmSourceImageId string

@description('Existing accelerator-owned user-assigned identity attached to the Slurm VM.')
param stagingIdentityResourceId string

@description('Client id of the staging identity, used by AzCopy managed-identity login.')
param stagingIdentityClientId string

@description('Existing accelerator-owned private HNS storage account resource id.')
param stagingStorageAccountId string

@description('Name of the existing private HNS storage account.')
param stagingStorageAccountName string

param inputContainerName string = 'healthcare'
param outputContainerName string = 'healthcare'
param logContainerName string = 'healthcare'

param addressSpace string = '10.43.0.0/16'
param privateEndpointSubnetPrefix string = '10.43.0.0/24'
param computeSubnetPrefix string = '10.43.1.0/24'
param lustreSubnetPrefix string = '10.43.2.0/24'
param slurmVmSize string = 'Standard_D4s_v7'
param slurmAvailabilityZone string = '1'
param amlfsAvailabilityZone string = '1'
param amlfsSkuName string = 'AMLFS-Durable-Premium-500'

@minValue(4)
param amlfsCapacityTiB int = 4

var tags = {
  project: 'genomics-variant-accelerator'
  component: 'hpc-campaign'
  lifecycle: 'ephemeral'
  campaignId: campaignId
  campaignOwner: campaignOwner
  expiresOn: expiresOn
}
var storageSuffix = az.environment().suffixes.storage

resource computeSecurity 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: 'nsg-hpc-${campaignId}'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'DenyInternetInbound'
        properties: {
          priority: 4096
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-hpc-${campaignId}'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        addressSpace
      ]
    }
    subnets: [
      {
        name: 'snet-private-endpoints'
        properties: {
          addressPrefix: privateEndpointSubnetPrefix
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'snet-compute'
        properties: {
          addressPrefix: computeSubnetPrefix
          networkSecurityGroup: {
            id: computeSecurity.id
          }
        }
      }
      {
        name: 'snet-managed-lustre'
        properties: {
          addressPrefix: lustreSubnetPrefix
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

resource blobPrivateZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.blob.${storageSuffix}'
  location: 'global'
  tags: tags
}

resource dfsPrivateZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.dfs.${storageSuffix}'
  location: 'global'
  tags: tags
}

resource blobZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: blobPrivateZone
  name: 'hpc-${campaignId}'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: network.id
    }
  }
}

resource dfsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: dfsPrivateZone
  name: 'hpc-${campaignId}'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: network.id
    }
  }
}

module blobPrivateEndpoint 'modules/private-endpoint.bicep' = {
  name: 'private-link-campaign-blob'
  params: {
    location: location
    tags: tags
    name: 'pe-hpc-${campaignId}-blob'
    subnetId: network.properties.subnets[0].id
    serviceId: stagingStorageAccountId
    groupId: 'blob'
    privateDnsZoneId: blobPrivateZone.id
  }
}

module dfsPrivateEndpoint 'modules/private-endpoint.bicep' = {
  name: 'private-link-campaign-dfs'
  params: {
    location: location
    tags: tags
    name: 'pe-hpc-${campaignId}-dfs'
    subnetId: network.properties.subnets[0].id
    serviceId: stagingStorageAccountId
    groupId: 'dfs'
    privateDnsZoneId: dfsPrivateZone.id
  }
}

module slurmScheduler 'modules/slurm-scheduler.bicep' = {
  name: 'slurm-scheduler'
  params: {
    location: location
    tags: tags
    name: 'vm-slurm-${campaignId}'
    subnetId: network.properties.subnets[1].id
    adminPublicKey: adminPublicKey
    vmSize: slurmVmSize
    userAssignedIdentityIds: [
      stagingIdentityResourceId
    ]
    sourceImageId: slurmSourceImageId
    zone: slurmAvailabilityZone
  }
}

module managedLustre 'modules/managed-lustre.bicep' = {
  name: 'managed-lustre'
  params: {
    location: location
    tags: tags
    name: 'amlfs-${campaignId}'
    subnetId: network.properties.subnets[2].id
    skuName: amlfsSkuName
    storageCapacityTiB: amlfsCapacityTiB
    zone: amlfsAvailabilityZone
  }
}

output campaignId string = campaignId
output campaignOwner string = campaignOwner
output slurmVmName string = slurmScheduler.outputs.vmName
output amlfsName string = managedLustre.outputs.filesystemName
output amlfsMountAddress string = managedLustre.outputs.mountAddress
output identityClientId string = stagingIdentityClientId
output storageAccountName string = stagingStorageAccountName
output inputContainerName string = inputContainerName
output outputContainerName string = outputContainerName
output logContainerName string = logContainerName
