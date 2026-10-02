metadata description = 'Ephemeral Azure Managed Lustre filesystem used only as campaign POSIX scratch.'

param location string
param tags object

@minLength(2)
@maxLength(80)
param name string

param subnetId string
param skuName string = 'AMLFS-Durable-Premium-500'

@minValue(4)
param storageCapacityTiB int = 4

param maintenanceDayOfWeek string = 'Saturday'
param maintenanceTimeUtc string = '22:00'
param zone string = '1'

resource filesystem 'Microsoft.StorageCache/amlFilesystems@2026-01-01' = {
  name: name
  location: location
  zones: [
    zone
  ]
  sku: {
    name: skuName
  }
  tags: tags
  properties: {
    filesystemSubnet: subnetId
    storageCapacityTiB: storageCapacityTiB
    maintenanceWindow: {
      dayOfWeek: maintenanceDayOfWeek
      timeOfDayUTC: maintenanceTimeUtc
    }
  }
}

output filesystemId string = filesystem.id
output filesystemName string = filesystem.name
output mountAddress string = filesystem.properties.clientInfo.mgsAddress
