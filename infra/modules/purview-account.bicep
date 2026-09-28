metadata description = 'Short-lived Microsoft Purview account for live lineage validation (task 3.4).'

param location string
param tags object

@minLength(3)
@maxLength(63)
@description('Purview account name. Must be globally unique.')
param accountName string

@description('Dedicated managed resource group for Purview-managed ingestion resources.')
param managedResourceGroupName string

@allowed([
  'Enabled'
  'Disabled'
  'NotSpecified'
])
param publicNetworkAccess string = 'Disabled'

@allowed([
  'Enabled'
  'Disabled'
  'NotSpecified'
])
param managedResourcesPublicNetworkAccess string = 'Disabled'

@allowed([
  'Enabled'
  'Disabled'
  'NotSpecified'
])
@description('Purview lineage ingestion requires the managed Event Hubs namespace when public access is disabled.')
param managedEventHubState string = 'Enabled'

resource account 'Microsoft.Purview/accounts@2021-12-01' = {
  name: accountName
  location: location
  tags: tags
  #disable-next-line BCP073
  sku: {
    name: 'Standard'
    capacity: 1
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publicNetworkAccess: publicNetworkAccess
    managedResourceGroupName: managedResourceGroupName
    managedResourcesPublicNetworkAccess: managedResourcesPublicNetworkAccess
    managedEventHubState: managedEventHubState
  }
}

output accountId string = account.id
output accountName string = account.name
output principalId string = account.identity.principalId
output catalogEndpoint string = account.properties.endpoints.catalog
output scanEndpoint string = account.properties.endpoints.scan
