import { IsDateString, IsInt, IsNumber, IsOptional, IsString, MaxLength, Min, MinLength } from 'class-validator';
import { Type } from 'class-transformer';

/**
 * CreateProductDto — generated from prisma/schema.prisma
 *
 * Fields:
 * - name: String
 * - description: String (optional)
 * - price: Float
 * - category: String
 * - stock: Int (optional)
 * - createdAt: DateTime (optional) */
export class CreateProductDto {
  @IsString()
  @MinLength(2)
  @MaxLength(200)
  name!: string;

  @IsOptional()
  @IsString()
  @MinLength(2)
  @MaxLength(200)
  description?: string;

  @IsNumber()
  @Min(0)
  @Type(() => Number)
  price!: number;

  @IsString()
  @MinLength(2)
  @MaxLength(200)
  category!: string;

  @IsOptional()
  @IsInt()
  @Min(0)
  stock?: number;

  @IsOptional()
  @IsDateString()
  createdAt?: string;
}
