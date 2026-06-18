import { PartialType } from '@nestjs/mapped-types';
import { CreateProductDto } from './create-product.dto';

/**
 * UpdateProductDto — all fields optional.
 * Inherits validation from CreateProductDto via PartialType.
 */
export class UpdateProductDto extends PartialType(CreateProductDto) {}
