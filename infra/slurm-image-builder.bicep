targetScope = 'resourceGroup'

param location string
param environment string
param buildId string
param sourceImageVersion string
param buildVmSize string = 'Standard_D4s_v7'
param buildSubnetPrefix string = '10.44.0.0/24'
param adminUsername string = 'azureuser'
@secure()
param adminPublicKey string

var tags = {
  project: 'genomics-variant-accelerator'
  component: 'hpc-image-build'
  environment: environment
  buildId: buildId
  lifecycle: 'ephemeral'
  buildMethod: 'trusted-launch-vm-capture'
}

resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: 'nsg-build-${buildId}'
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

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-build-${buildId}'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.44.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'snet-build'
        properties: {
          addressPrefix: buildSubnetPrefix
          defaultOutboundAccess: true
          networkSecurityGroup: {
            id: nsg.id
          }
        }
      }
    ]
  }
}

resource nic 'Microsoft.Network/networkInterfaces@2024-05-01' = {
  name: 'nic-build-${buildId}'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: {
            id: vnet.properties.subnets[0].id
          }
        }
      }
    ]
  }
}

resource buildVm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
  name: 'vm-build-${buildId}'
  location: location
  tags: union(tags, {
    sourceImage: 'Canonical:ubuntu-24_04-lts:server:${sourceImageVersion}'
    secureBoot: 'required'
    vtpm: 'required'
  })
  properties: {
    hardwareProfile: {
      vmSize: buildVmSize
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: sourceImageVersion
      }
      osDisk: {
        createOption: 'FromImage'
        managedDisk: {
          storageAccountType: 'Premium_LRS'
        }
        diskSizeGB: 64
      }
    }
    osProfile: {
      computerName: 'vm-build-${buildId}'
      adminUsername: adminUsername
      linuxConfiguration: {
        disablePasswordAuthentication: true
        ssh: {
          publicKeys: [
            {
              path: '/home/azureuser/.ssh/authorized_keys'
              keyData: adminPublicKey
            }
          ]
        }
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: nic.id
          properties: {
            primary: true
          }
        }
      ]
    }
    securityProfile: {
      securityType: 'TrustedLaunch'
      uefiSettings: {
        secureBootEnabled: true
        vTpmEnabled: true
      }
    }
  }
}

output buildVmId string = buildVm.id
output buildVmName string = buildVm.name
output buildSubnetId string = vnet.properties.subnets[0].id
