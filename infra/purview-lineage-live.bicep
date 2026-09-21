targetScope = 'resourceGroup'

metadata description = 'Short-lived private Microsoft Purview deployment for live lineage verification (task 3.4).'

param location string
param tags object

@minLength(3)
@maxLength(63)
param purviewAccountName string

param purviewManagedResourceGroupName string
param privateEndpointSubnetId string
param virtualNetworkId string

@description('Existing Data Factory to connect to Purview for lineage push.')
param dataFactoryName string

@description('Existing user-assigned identity resource id attached to the Data Factory for landing reads.')
param dataFactoryIngestionIdentityId string

@description('Existing user-assigned identity resource id attached to the Data Factory for lake writes.')
param dataFactoryStagingIdentityId string

@description('Purview-managed ingestion storage account resource id, supplied on the second deployment pass after the account exists.')
param purviewManagedStorageAccountId string = ''

@description('Purview-managed Event Hubs namespace resource id, supplied on the second deployment pass after the account exists.')
param purviewManagedEventHubNamespaceId string = ''

var purviewPrivateDnsZoneName = 'privatelink.purview.azure.com'
var purviewPlatformPrivateDnsZoneName = 'privatelink.purview-service.microsoft.com'

module purviewAccount 'modules/purview-account.bicep' = {
  name: 'purview-account'
  params: {
    location: location
    tags: tags
    accountName: purviewAccountName
    managedResourceGroupName: purviewManagedResourceGroupName
  }
}

resource purviewPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: purviewPrivateDnsZoneName
  location: 'global'
  tags: tags
}

resource purviewZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: purviewPrivateDnsZone
  name: '${purviewAccountName}-link'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

resource purviewPlatformPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: purviewPlatformPrivateDnsZoneName
  location: 'global'
  tags: tags
}

resource purviewPlatformZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: purviewPlatformPrivateDnsZone
  name: '${purviewAccountName}-link'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetworkId
    }
  }
}

module purviewAccountEndpoint 'modules/private-endpoint.bicep' = {
  name: 'purview-account-private-link'
  params: {
    location: location
    tags: tags
    name: 'pe-${purviewAccountName}-account'
    subnetId: privateEndpointSubnetId
    serviceId: purviewAccount.outputs.accountId
    groupId: 'account'
    privateDnsZoneId: purviewPrivateDnsZone.id
  }
}

module purviewPlatformEndpoint 'modules/private-endpoint.bicep' = {
  name: 'purview-platform-private-link'
  params: {
    location: location
    tags: tags
    name: 'pe-${purviewAccountName}-platform'
    subnetId: privateEndpointSubnetId
    serviceId: purviewAccount.outputs.accountId
    groupId: 'platform'
    privateDnsZoneId: purviewPlatformPrivateDnsZone.id
  }
}

resource dataFactory 'Microsoft.DataFactory/factories@2018-06-01' = {
  name: dataFactoryName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned,UserAssigned'
    userAssignedIdentities: {
      '${dataFactoryIngestionIdentityId}': {}
      '${dataFactoryStagingIdentityId}': {}
    }
  }
  properties: {
    publicNetworkAccess: 'Disabled'
    purviewConfiguration: {
      purviewResourceId: purviewAccount.outputs.accountId
    }
  }
}

resource managedNetwork 'Microsoft.DataFactory/factories/managedVirtualNetworks@2018-06-01' existing = {
  parent: dataFactory
  name: 'default'
}

resource purviewAccountManagedEndpoint 'Microsoft.DataFactory/factories/managedVirtualNetworks/managedPrivateEndpoints@2018-06-01' = {
  parent: managedNetwork
  name: 'purview-account'
  properties: {
    privateLinkResourceId: purviewAccount.outputs.accountId
    groupId: 'account'
  }
}

resource purviewPlatformManagedEndpoint 'Microsoft.DataFactory/factories/managedVirtualNetworks/managedPrivateEndpoints@2018-06-01' = {
  parent: managedNetwork
  name: 'purview-platform'
  properties: {
    privateLinkResourceId: purviewAccount.outputs.accountId
    groupId: 'platform'
  }
}

resource purviewBlobManagedEndpoint 'Microsoft.DataFactory/factories/managedVirtualNetworks/managedPrivateEndpoints@2018-06-01' = if (!empty(purviewManagedStorageAccountId)) {
  parent: managedNetwork
  name: 'purview-ingestion-blob'
  properties: {
    privateLinkResourceId: purviewManagedStorageAccountId
    groupId: 'blob'
  }
}

resource purviewQueueManagedEndpoint 'Microsoft.DataFactory/factories/managedVirtualNetworks/managedPrivateEndpoints@2018-06-01' = if (!empty(purviewManagedStorageAccountId)) {
  parent: managedNetwork
  name: 'purview-ingestion-queue'
  properties: {
    privateLinkResourceId: purviewManagedStorageAccountId
    groupId: 'queue'
  }
}

resource purviewEventHubManagedEndpoint 'Microsoft.DataFactory/factories/managedVirtualNetworks/managedPrivateEndpoints@2018-06-01' = if (!empty(purviewManagedEventHubNamespaceId)) {
  parent: managedNetwork
  name: 'purview-ingestion-eventhub'
  properties: {
    privateLinkResourceId: purviewManagedEventHubNamespaceId
    groupId: 'namespace'
  }
}

output purviewAccountId string = purviewAccount.outputs.accountId
output purviewAccountName string = purviewAccount.outputs.accountName
output purviewPrincipalId string = purviewAccount.outputs.principalId
output purviewCatalogEndpoint string = purviewAccount.outputs.catalogEndpoint
output purviewScanEndpoint string = purviewAccount.outputs.scanEndpoint
output purviewManagedResourceGroupName string = purviewManagedResourceGroupName
output purviewManagedStorageAccountId string = purviewManagedStorageAccountId
output purviewManagedEventHubNamespaceId string = purviewManagedEventHubNamespaceId
output dataFactoryPrincipalId string = dataFactory.identity.principalId
output dataFactoryPurviewAccountManagedPrivateEndpointName string = purviewAccountManagedEndpoint.name
output dataFactoryPurviewPlatformManagedPrivateEndpointName string = purviewPlatformManagedEndpoint.name
output dataFactoryPurviewBlobManagedPrivateEndpointName string = empty(purviewManagedStorageAccountId) ? '' : purviewBlobManagedEndpoint.name
output dataFactoryPurviewQueueManagedPrivateEndpointName string = empty(purviewManagedStorageAccountId) ? '' : purviewQueueManagedEndpoint.name
output dataFactoryPurviewEventHubManagedPrivateEndpointName string = empty(purviewManagedEventHubNamespaceId) ? '' : purviewEventHubManagedEndpoint.name
