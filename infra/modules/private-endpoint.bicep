metadata description = 'Private endpoint plus private DNS registration for one storage sub-resource.'

param location string
param tags object
param name string
param subnetId string
param serviceId string

@description('Storage sub-resource to expose, such as file, blob or dfs.')
param groupId string

param privateDnsZoneId string

resource endpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: groupId
        properties: {
          privateLinkServiceId: serviceId
          groupIds: [
            groupId
          ]
        }
      }
    ]
  }
}

resource registration 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: groupId
        properties: {
          privateDnsZoneId: privateDnsZoneId
        }
      }
    ]
  }
}

output privateEndpointName string = endpoint.name
