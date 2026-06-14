import {
  Controller,
  Get,
  Post,
  Body,
  Patch,
  Param,
  Delete,
  Query,
  ParseIntPipe,
  ParseFloatPipe,
} from '@nestjs/common';
import { ProductService } from './product.service';
import { CreateProductDto } from './dto/create-product.dto';
import { UpdateProductDto } from './dto/update-product.dto';
import { Product } from '@prisma/client';

@Controller('products')
export class ProductController {
  constructor(private readonly productService: ProductService) {}

  @Post()
  create(@Body() createProductDto: CreateProductDto): Promise<Product> {
    return this.productService.create(createProductDto);
  }

  @Get()
  findAll(): Promise<Product[]> {
    return this.productService.findAll();
  }

  // ── Business-logic endpoints (call service methods that reference
  //    individual schema fields — the Agent tracks these on schema change) ──

  @Get('in-stock')
  findInStock(): Promise<Product[]> {
    return this.productService.findInStock();
  }

  @Get('category/:category')
  findByCategory(@Param('category') category: string): Promise<Product[]> {
    return this.productService.findByCategory(category);
  }

  @Get('price-range')
  findByPriceRange(
    @Query('min', ParseFloatPipe) min: number,
    @Query('max', ParseFloatPipe) max: number,
  ): Promise<Product[]> {
    return this.productService.findByPriceRange(min, max);
  }

  @Patch(':id/restock')
  restock(
    @Param('id', ParseIntPipe) id: number,
    @Body('amount', ParseIntPipe) amount: number,
  ): Promise<Product> {
    return this.productService.restockProduct(id, amount);
  }

  // ── Standard CRUD endpoints ──

  @Get(':id')
  findOne(@Param('id', ParseIntPipe) id: number): Promise<Product> {
    return this.productService.findOne(id);
  }

  @Patch(':id')
  update(
    @Param('id', ParseIntPipe) id: number,
    @Body() updateProductDto: UpdateProductDto,
  ): Promise<Product> {
    return this.productService.update(id, updateProductDto);
  }

  @Delete(':id')
  remove(@Param('id', ParseIntPipe) id: number): Promise<Product> {
    return this.productService.remove(id);
  }
}
