data "openstack_images_image_v2" "kali" {
  name        = var.image_name
  most_recent = true
}

data "openstack_images_image_v2" "victim" {
  name        = var.victim_image_name
  most_recent = true
}
