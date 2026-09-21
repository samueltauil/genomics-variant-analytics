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
param ingestionStoragePublicNetworkAccess string = 'Disabled'

@allowed([
  'Enabled'
  'Disabled'
  'NotSpecified'
])
@description('Leave Event Hubs in its default state; task 3.4 only requires Copy-activity lineage, not Kafka notifications.')
param managedEventHubState string = 'NotSpecified'

resource account 'Microsoft.Purview/accounts@2023-05-01-preview' = {
  name: accountName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publicNetworkAccess: publicNetworkAccess
    managedResourceGroupName: managedResourceGroupName
    managedResourcesPublicNetworkAccess: managedResourcesPublicNetworkAccess
    managedEventHubState: managedEventHubState
    ingestionStorage: {
      publicNetworkAccess: ingestionStoragePublicNetworkAccess
    }
  }
}

output accountId string = account.id
output accountName string = account.name
output principalId string = account.identity.principalId
output catalogEndpoint string = account.properties.endpoints.catalog
output scanEndpoint string = account.properties.endpoints.scan
