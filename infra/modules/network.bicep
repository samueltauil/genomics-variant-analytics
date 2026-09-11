metadata description = 'Private network for the accelerator. Governance requires storage data planes to be private (task 8.7).'

param location string
param tags object
param namePrefix string

@description('Address space for the environment. Isolated from any laboratory range.')
param addressSpace string = '10.42.0.0/16'

param privateEndpointSubnetPrefix string = '10.42.0.0/24'
param computeSubnetPrefix string = '10.42.1.0/24'

var storageSuffix = az.environment().suffixes.storage
var privateZoneNames = [
  'privatelink.file.${storageSuffix}'
  'privatelink.blob.${storageSuffix}'
  'privatelink.dfs.${storageSuffix}'
]

resource computeSecurity 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${namePrefix}-compute-nsg'
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

// Governance blocks public IP addresses in this subscription, so NAT Gateway, Azure Firewall and
// VM public addresses are all unavailable. The client reaches Azure only over private endpoints and
// is driven through run-command, which needs no outbound internet path.
resource network 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${namePrefix}-vnet'
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
    ]
  }
}

resource privateZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [
  for zone in privateZoneNames: {
    name: zone
    location: 'global'
    tags: tags
  }
]

resource zoneLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [
  for (zone, index) in privateZoneNames: {
    parent: privateZones[index]
    name: '${namePrefix}-link'
    location: 'global'
    tags: tags
    properties: {
      registrationEnabled: false
      virtualNetwork: {
        id: network.id
      }
    }
  }
]

output virtualNetworkId string = network.id
output privateEndpointSubnetId string = network.properties.subnets[0].id
output computeSubnetId string = network.properties.subnets[1].id
output fileZoneId string = privateZones[0].id
output blobZoneId string = privateZones[1].id
output dfsZoneId string = privateZones[2].id
